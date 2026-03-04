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
    incoming = _normalize_number(message.from_number)
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
                # Usar AI para detectar si eligió un horario
                for idx, slot in enumerate(conversation.proposed_times):
                    if str(idx + 1) in text or slot['day'].lower() in text.lower():
                        conversation.selected_time = slot["display"]
                        conversation.proposed_times.insert(0, slot)
                        print(f"[SAVED] Horario: {conversation.selected_time}")
                        break

            state.set_appointment_conversation(incoming, conversation)

            # Si ya tenemos TODO (doctor, ubicación, horario) → CREAR CITA
            if conversation.selected_doctor and conversation.selected_office and conversation.selected_time:
                print(f"[CREATING APPOINTMENT] Doctor={conversation.selected_doctor} Location={conversation.selected_office} Time={conversation.selected_time}")

                response_text = (
                    f"Perfecto! He agendado tu cita con {DOCTORS[conversation.selected_doctor]} "
                    f"para {conversation.selected_time} en {OFFICE_LOCATIONS[conversation.selected_office]}.\n\n"
                    f"Te esperamos ese día. Si necesitas reagendar o tienes alguna duda, escríbeme."
                )

                # Crear evento en Google Calendar
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

                    await calendar.create_event(event_payload)
                    state.log_event("appointment.created", f"patient={incoming} doctor={conversation.selected_doctor} time={conversation.selected_time} office={conversation.selected_office}")

                    # Limpiar conversación
                    state.clear_appointment_conversation(incoming)
                except Exception as exc:
                    state.log_event("appointment.error", f"patient={incoming} error={str(exc)}")
                    response_text += "\n\n(Nota: Hubo un problema al crear el evento en el calendario, pero tu cita está confirmada)"

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
