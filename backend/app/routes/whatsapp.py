from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..config import settings
from ..schemas import IncomingWhatsAppMessage, OutgoingWhatsAppMessage, CalendarEventDraft
from ..services.whatsapp_gateway import WhatsAppGateway
from ..services.calendar import CalendarClient
from ..services.ai import AIClient
from ..state import state, AppointmentConversation

router = APIRouter()
gateway = WhatsAppGateway()

DOCTORS = {
    "fernandez": "Dr. Jose Fernandez (Consultas Generales)",
    "paredes": "Dr. Juan Paredes (Pediatría)",
    "perez": "Dr. Pedro Perez (Neurología)",
}

OFFICE_LOCATIONS = {
    "calle13": "Calle 13, Número 111",
    "calle09": "Calle 09, Número 120",
}

# SOLUCIÓN MEDIA: Ubicación por defecto si no se especifica
DEFAULT_OFFICE = "calle13"  # Sede principal


def _normalize_number(raw: str) -> str:
    # Strip non-digits, keep number as-is for WhatsApp
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    return digits


@router.post("/whatsapp/incoming")
async def whatsapp_incoming(message: IncomingWhatsAppMessage):
    """
    Health counselor bot - accepts ALL incoming WhatsApp messages,
    analyzes them as health queries, and responds automatically.
    """
    print(f"[RAW FROM_NUMBER] raw={message.from_number}")
    incoming = _normalize_number(message.from_number)
    print(f"[NORMALIZED] normalized={incoming}")
    state.log_event("whatsapp.incoming", f"from={message.from_number} text={message.text[:100]}")

    try:
        ai = AIClient(settings.openai_api_key)
        text = message.text.lower().strip()

        # Guardar mensaje del usuario en historial
        state.add_message_to_history(incoming, "user", message.text)

        # Obtener historial conversacional
        history = state.get_conversation_history(incoming)

        # Obtener conversación de agendamiento si hay una
        conversation = state.get_appointment_conversation(incoming)

        # FLUJO CONVERSACIONAL INTELIGENTE
        # Extraer información de la conversación completa usando AI
        appointment_info = await ai.extract_appointment_info(history)

        print(f"[AI EXTRACTION] patient={incoming} info={appointment_info}")
        state.log_event("ai.extraction", f"patient={incoming} wants_appt={appointment_info.get('wants_appointment')} doctor={appointment_info.get('recommended_doctor')}")

        # Guardar información extraída en la conversación
        if not conversation and appointment_info.get('wants_appointment'):
            # Crear nueva conversación de agendamiento
            conversation = AppointmentConversation(
                patient_number=incoming,
                state="conversing",
                symptoms=appointment_info.get('symptoms_summary', '')
            )

        # Si hay conversación activa, actualizar con info extraída por AI
        if conversation:
            # GUARDAR valores extraídos por AI
            if appointment_info.get('recommended_doctor') and not conversation.selected_doctor:
                conversation.selected_doctor = appointment_info['recommended_doctor']
                print(f"[SAVED] Doctor: {conversation.selected_doctor}")

            if appointment_info.get('preferred_location') and not conversation.selected_office:
                conversation.selected_office = appointment_info['preferred_location']
                print(f"[SAVED] Ubicación: {conversation.selected_office}")

            if appointment_info.get('symptoms_summary'):
                conversation.symptoms = appointment_info['symptoms_summary']

            # Verificar si eligió horario de la lista propuesta
            if conversation.proposed_times and not conversation.selected_time:
                # SOLUCIÓN: Usar LLM para detectar si REALMENTE eligió un horario (el cliente manda!)
                selection_prompt = f"El usuario respondió: '{text}'\n\nOpciones disponibles:\n"
                for idx, slot in enumerate(conversation.proposed_times, 1):
                    selection_prompt += f"{idx}. {slot['display']}\n"
                selection_prompt += (
                    "\n¿El usuario ACEPTÓ una de estas opciones? "
                    "Responde SOLO con el número (1-5) si aceptó. "
                    "Si RECHAZÓ, pidió otra fecha, o no eligió ninguna, responde 'ninguna'."
                )

                try:
                    selection_response = await ai.client.chat.completions.create(
                        model=ai.model,
                        messages=[{"role": "user", "content": selection_prompt}],
                        max_tokens=10
                    )
                    selected_num = selection_response.choices[0].message.content.strip().lower()
                    print(f"[LLM SLOT SELECTION] User: '{text}' → LLM: '{selected_num}'")

                    if selected_num.isdigit() and 1 <= int(selected_num) <= len(conversation.proposed_times):
                        idx = int(selected_num) - 1
                        slot = conversation.proposed_times[idx]
                        conversation.selected_time = slot["display"]
                        conversation.proposed_times.insert(0, slot)
                        print(f"[SAVED] Horario: {conversation.selected_time}")
                    else:
                        # Usuario rechazó o pidió otra fecha → LIMPIAR slots para buscar nuevos
                        print(f"[NO SLOT SELECTED] User rejected or asked for different date - clearing proposed_times")
                        conversation.proposed_times = []
                        state.set_appointment_conversation(incoming, conversation)
                except Exception as e:
                    print(f"[ERROR] LLM slot selection failed: {e}")

            state.set_appointment_conversation(incoming, conversation)

            # SOLUCIÓN MEDIA: Si tiene doctor + horario pero falta ubicación → usar default
            if conversation.selected_doctor and conversation.selected_time and not conversation.selected_office:
                conversation.selected_office = DEFAULT_OFFICE
                print(f"[USING DEFAULT OFFICE] {DEFAULT_OFFICE}")
                state.set_appointment_conversation(incoming, conversation)

            # SOLUCIÓN CORTA: Verificar qué falta y preguntar específicamente
            missing = []
            if not conversation.selected_doctor:
                missing.append("doctor")
            if not conversation.selected_office:
                missing.append("ubicación")
            if not conversation.selected_time:
                missing.append("horario")

            # Si falta algo, preguntar por el primer elemento faltante
            if missing:
                print(f"[MISSING INFO] Missing: {missing}")
                if "doctor" in missing:
                    doctor_options = "\n".join([f"- {DOCTORS[key]}" for key in DOCTORS.keys()])
                    response_text = (
                        f"Entiendo que necesitas una cita. ¿Con cuál de nuestros especialistas te gustaría agendar?\n\n"
                        f"{doctor_options}"
                    )
                    await gateway.send_message(
                        OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                    )
                    state.add_message_to_history(incoming, "assistant", response_text)
                    return {"status": "asking_doctor"}
                elif "ubicación" in missing:
                    location_options = "\n".join([f"- {OFFICE_LOCATIONS[key]}" for key in OFFICE_LOCATIONS.keys()])
                    response_text = (
                        f"Perfecto! Tenemos tu cita con {DOCTORS[conversation.selected_doctor]}"
                        f"{' para ' + conversation.selected_time if conversation.selected_time else ''}.\n\n"
                        f"¿En cuál consultorio prefieres tu cita?\n\n{location_options}"
                    )
                    await gateway.send_message(
                        OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                    )
                    state.add_message_to_history(incoming, "assistant", response_text)
                    return {"status": "asking_ubicación"}
                elif "horario" in missing and not conversation.proposed_times:
                    # FLUJO CONVERSACIONAL: Extraer fecha/hora que el usuario está pidiendo
                    print(f"[EXTRACTING DATETIME REQUEST]")
                    datetime_request = await ai.extract_datetime_request(history)
                    print(f"[DATETIME REQUEST] {datetime_request}")

                    # Si falta horario Y no hemos ofrecido slots → BUSCAR disponibilidad
                    print(f"[CHECKING AVAILABILITY for requested datetime]")
                    try:
                        calendar = CalendarClient()
                        tz = ZoneInfo(settings.scheduler_timezone)
                        now = datetime.now(tz)

                        # Determinar rango de búsqueda basado en lo que pidió el usuario
                        if datetime_request.get('requested_date'):
                            # Pidió fecha específica → buscar solo ese día
                            search_date = datetime.fromisoformat(datetime_request['requested_date']).replace(tzinfo=tz)
                            start_date = search_date
                            end_date = search_date + timedelta(days=1)
                            print(f"[SEARCHING SPECIFIC DATE] {datetime_request['requested_date']}")
                        elif datetime_request.get('requested_day_name'):
                            # Pidió día de la semana → buscar próximo día con ese nombre
                            day_map = {"lunes": 0, "martes": 1, "miércoles": 2, "jueves": 3, "viernes": 4, "sábado": 5, "domingo": 6}
                            requested_weekday = day_map.get(datetime_request['requested_day_name'].lower())
                            if requested_weekday is not None:
                                days_ahead = (requested_weekday - now.weekday()) % 7
                                if days_ahead == 0:
                                    days_ahead = 7  # Próxima semana si es hoy
                                search_date = now + timedelta(days=days_ahead)
                                start_date = search_date.replace(hour=0, minute=0, second=0, microsecond=0)
                                end_date = start_date + timedelta(days=1)
                                print(f"[SEARCHING WEEKDAY] {datetime_request['requested_day_name']} → {search_date.strftime('%Y-%m-%d')}")
                            else:
                                # Fallback: buscar próximos 7 días
                                start_date = now
                                end_date = now + timedelta(days=7)
                        else:
                            # No especificó → buscar próximos 7 días
                            start_date = now
                            end_date = now + timedelta(days=7)

                        # Ajustar para suggest_available_slots que usa "días desde hoy"
                        # Si buscamos un día específico en el futuro, calcular días desde hoy
                        if datetime_request.get('requested_date') or datetime_request.get('requested_day_name'):
                            # Buscar solo ese día específico
                            days_until = max(0, (start_date.replace(hour=0, minute=0, second=0, microsecond=0) - now.replace(hour=0, minute=0, second=0, microsecond=0)).days)
                            days_range = 1
                        else:
                            # Búsqueda general de 7 días
                            days_until = 0
                            days_range = 7

                        existing_events = await calendar.list_events(start_date, end_date)

                        # Filtrar slots para obtener solo el rango que nos interesa
                        all_slots = await ai.suggest_available_slots(
                            existing_events,
                            settings.scheduler_timezone,
                            days_ahead=7  # Buscar en ventana amplia
                        )

                        # Filtrar slots para el día específico si lo pidió
                        if datetime_request.get('requested_date'):
                            target_date = datetime_request['requested_date']
                            available_slots = [s for s in all_slots if s['date'] == target_date]
                        elif datetime_request.get('requested_day_name'):
                            target_day = datetime_request['requested_day_name'].capitalize()
                            available_slots = [s for s in all_slots if s['day'] == target_day]
                        else:
                            available_slots = all_slots

                        if available_slots:
                            conversation.proposed_times = available_slots[:5]
                            state.set_appointment_conversation(incoming, conversation)

                            doctor_text = f" con {DOCTORS[conversation.selected_doctor]}" if conversation.selected_doctor else ""
                            location_text = f" en {OFFICE_LOCATIONS[conversation.selected_office]}" if conversation.selected_office else ""

                            # CONVERSACIONAL: Si pidió hora específica y la tenemos, confirmarla directamente
                            requested_time = datetime_request.get('requested_time')
                            if requested_time:
                                # Buscar si tenemos exactamente esa hora
                                exact_match = next((slot for slot in available_slots if slot['time'] == requested_time), None)
                                if exact_match:
                                    # ¡Encontramos exactamente lo que pidió!
                                    response_text = (
                                        f"¡Perfecto{doctor_text}{location_text}! "
                                        f"Tengo disponible {exact_match['display']}. ¿Te parece bien ese horario?"
                                    )
                                else:
                                    # Tenemos el día pero no esa hora específica
                                    options_text = f"Para {datetime_request.get('requested_day_name', 'ese día')} tengo:\n\n"
                                    for idx, slot in enumerate(available_slots[:5], 1):
                                        options_text += f"{idx}. {slot['display']}\n"
                                    response_text = (
                                        f"Lo siento, {datetime_request.get('requested_day_name', 'ese día')} a las {requested_time} ya está ocupado. "
                                        f"Pero tengo otras opciones:\n\n{options_text}\n¿Cuál te conviene?"
                                    )
                            else:
                                # No pidió hora específica, mostrar opciones
                                options_text = "Tengo disponibilidad en:\n\n"
                                for idx, slot in enumerate(available_slots[:5], 1):
                                    options_text += f"{idx}. {slot['display']}\n"
                                response_text = f"Perfecto{doctor_text}{location_text}. {options_text}\n¿Cuál horario prefieres?"

                            await gateway.send_message(
                                OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                            )
                            state.add_message_to_history(incoming, "assistant", response_text)
                            return {"status": "offered_slots"}
                        else:
                            # No hay disponibilidad para lo que pidió
                            if datetime_request.get('requested_day_name') or datetime_request.get('requested_date'):
                                day_text = datetime_request.get('requested_day_name', datetime_request.get('requested_date', 'ese día'))
                                response_text = (
                                    f"Lo siento, no tengo disponibilidad para {day_text}. "
                                    f"¿Te gustaría que busque en otros días cercanos?"
                                )
                            else:
                                response_text = "Déjame revisar mi agenda... Actualmente no tengo horarios disponibles en los próximos días. ¿Podrías llamarme directamente?"
                            await gateway.send_message(
                                OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                            )
                            state.add_message_to_history(incoming, "assistant", response_text)
                            return {"status": "no_slots"}

                    except Exception as exc:
                        import traceback
                        print(f"[CALENDAR ERROR] {traceback.format_exc()}")
                        response_text = "Disculpa, dame un momento para revisar mi agenda. Si es urgente, puedes llamarme directamente."
                        await gateway.send_message(
                            OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                        )
                        state.add_message_to_history(incoming, "assistant", response_text)
                        return {"status": "calendar_error"}

            # Si ya tenemos TODO (doctor, ubicación, horario) → CREAR CITA
            if conversation.selected_doctor and conversation.selected_office and conversation.selected_time:
                print(f"[CREATING APPOINTMENT] Doctor={conversation.selected_doctor} Location={conversation.selected_office} Time={conversation.selected_time}")

                # Crear evento en Google Calendar PRIMERO
                try:
                    calendar = CalendarClient()

                    # Parsear el datetime seleccionado
                    slot_dt = datetime.fromisoformat(conversation.proposed_times[0]["datetime"])
                    end_dt = slot_dt + timedelta(hours=1)

                    # Crear payload en formato Google Calendar API
                    event_payload = {
                        "summary": f"{DOCTORS[conversation.selected_doctor]} - {incoming}",
                        "start": {
                            "dateTime": slot_dt.isoformat(),
                            "timeZone": settings.scheduler_timezone
                        },
                        "end": {
                            "dateTime": end_dt.isoformat(),
                            "timeZone": settings.scheduler_timezone
                        },
                        "location": OFFICE_LOCATIONS[conversation.selected_office],
                        "description": f"Paciente: {incoming}\nDoctor: {DOCTORS[conversation.selected_doctor]}\nMotivo: {conversation.symptoms or 'No especificado'}",
                    }

                    result = await calendar.create_event(event_payload)
                    print(f"[CALENDAR SUCCESS] Event created: {result.get('id')}")
                    state.log_event("appointment.created", f"patient={incoming} doctor={conversation.selected_doctor} time={conversation.selected_time} office={conversation.selected_office}")

                    # SOLO si Google Calendar respondió exitosamente → CONFIRMAR
                    response_text = (
                        f"✅ Perfecto! He agendado tu cita con {DOCTORS[conversation.selected_doctor]} "
                        f"para {conversation.selected_time} en {OFFICE_LOCATIONS[conversation.selected_office]}.\n\n"
                        f"Te esperamos ese día. Si necesitas reagendar o tienes alguna duda, escríbeme."
                    )

                    # Limpiar conversación
                    state.clear_appointment_conversation(incoming)
                    print(f"[CLEARED] Appointment conversation after successful booking")

                except Exception as exc:
                    import traceback
                    error_detail = traceback.format_exc()
                    print(f"[CALENDAR ERROR] {error_detail}")
                    state.log_event("appointment.error", f"patient={incoming} error={str(exc)}")

                    # Si falla, NO confirmar la cita
                    response_text = (
                        f"Lo siento, tuve un problema al crear tu cita en el sistema. "
                        f"Por favor intenta de nuevo o llámanos directamente al hospital. "
                        f"Disculpa las molestias."
                    )

                await gateway.send_message(
                    OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                )

                # Guardar respuesta en historial
                state.add_message_to_history(incoming, "assistant", response_text)

                return {"status": "appointment_confirmed"}

            # Si estamos listos para ofrecer horarios pero aún no los hemos ofrecido
            elif appointment_info.get('ready_to_offer_slots') and not conversation.proposed_times:
                print(f"[OFFERING SLOTS] Patient ready to see available times")
                try:
                    calendar = CalendarClient()
                    tz = ZoneInfo(settings.scheduler_timezone)
                    now = datetime.now(tz)
                    start_date = now
                    end_date = now + timedelta(days=7)

                    existing_events = await calendar.list_events(start_date, end_date)
                    available_slots = await ai.suggest_available_slots(
                        existing_events,
                        settings.scheduler_timezone,
                        days_ahead=7
                    )

                    if available_slots:
                        conversation.proposed_times = available_slots[:5]
                        state.set_appointment_conversation(incoming, conversation)

                        # Respuesta conversacional con opciones
                        doctor_text = f" con {DOCTORS[conversation.selected_doctor]}" if conversation.selected_doctor else ""
                        location_text = f" en {OFFICE_LOCATIONS[conversation.selected_office]}" if conversation.selected_office else ""

                        options_text = "Tengo disponibilidad en:\n\n"
                        for idx, slot in enumerate(available_slots[:5], 1):
                            options_text += f"{idx}. {slot['display']}\n"

                        response_text = f"Perfecto{doctor_text}{location_text}. {options_text}\n¿Cuál horario prefieres?"

                        await gateway.send_message(
                            OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                        )
                        state.add_message_to_history(incoming, "assistant", response_text)
                        return {"status": "offered_slots"}
                    else:
                        response_text = "Déjame revisar mi agenda... Actualmente no tengo horarios disponibles en los próximos días. ¿Podrías llamarme directamente?"
                        await gateway.send_message(
                            OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                        )
                        state.add_message_to_history(incoming, "assistant", response_text)
                        return {"status": "no_slots"}

                except Exception as exc:
                    import traceback
                    print(f"[CALENDAR ERROR] {traceback.format_exc()}")
                    response_text = "Disculpa, dame un momento para revisar mi agenda. Si es urgente, puedes llamarme directamente."
                    await gateway.send_message(
                        OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                    )
                    state.add_message_to_history(incoming, "assistant", response_text)
                    return {"status": "calendar_error"}

        # No hay conversación activa o está en estado inicial - usar respuesta conversacional del LLM
        print(f"[DEFAULT RESPONSE PATH] No conversation or not offering slots, using analyze_health_query")
        analysis = await ai.analyze_health_query(message.text, conversation_history=history)
        print(f"[ANALYSIS RESULT] emergency={analysis.get('is_emergency')} needs_appt={analysis.get('needs_appointment')} response={analysis.get('suggested_response', '')[:100]}")

        is_emergency = analysis.get("is_emergency", False)
        needs_appointment = analysis.get("needs_appointment", False)
        needs_more_info = analysis.get("needs_more_info", False)
        suggested_response = analysis.get("suggested_response", "Entiendo tu consulta. ¿Cómo puedo ayudarte?")
        urgency = analysis.get("urgency", "low")

        state.log_event(
            "health.analysis",
            f"from={incoming} emergency={is_emergency} needs_appt={needs_appointment} urgency={urgency}",
        )

        # Usar respuesta conversacional del LLM
        response_text = suggested_response
        print(f"[SENDING RESPONSE] to={incoming} text={response_text[:100]}")

        # Si es emergencia, loguear
        if is_emergency:
            state.log_event("health.emergency", f"from={incoming} message={message.text[:50]}")

        # Enviar respuesta
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=message.from_number,
                text=response_text,
            )
        )

        # Guardar respuesta en historial
        state.add_message_to_history(incoming, "assistant", response_text)

        state.log_event("whatsapp.response_sent", f"to={incoming} emergency={is_emergency} appt={needs_appointment}")

        return {
            "status": "processed",
            "emergency": is_emergency,
            "needs_appointment": needs_appointment,
            "urgency": urgency,
        }

    except Exception as exc:
        import traceback
        error_detail = traceback.format_exc()
        state.log_event("whatsapp.error", f"from={incoming} error={str(exc)} traceback={error_detail[:500]}")
        # En caso de error, enviar respuesta genérica
        try:
            error_response = "Disculpa, estoy teniendo problemas técnicos. Por favor intenta de nuevo o llama al doctor directamente si es urgente."
            await gateway.send_message(
                OutgoingWhatsAppMessage(
                    to_number=message.from_number,
                    text=error_response,
                )
            )
            state.add_message_to_history(incoming, "assistant", error_response)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(exc))
