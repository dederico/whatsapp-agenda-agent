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

OFFICE_LOCATIONS = {
    "muguerza": "Hospital Muguerza Alta Especialidad, Av. Hidalgo 2525, Monterrey, N.L.",
    "zambrano": "Hospital Zambrano Hellion, San Pedro Garza García, N.L.",
    "imss": "IMSS, Monterrey, N.L.",
}


def _normalize_number(raw: str) -> str:
    # Strip non-digits and normalize MX mobile (52/521) prefixes.
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if digits.startswith("521"):
        return "52" + digits[3:]
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

        # Si hay una conversación de agendamiento activa
        if conversation:
            # Estado: eligiendo consultorio
            if conversation.state == "choosing_office":
                selected_office = None
                if "muguerza" in text:
                    selected_office = "muguerza"
                elif "zambrano" in text:
                    selected_office = "zambrano"
                elif "imss" in text:
                    selected_office = "imss"

                if selected_office:
                    conversation.selected_office = selected_office
                    conversation.state = "confirming"
                    state.set_appointment_conversation(incoming, conversation)

                    response_text = (
                        f"Perfecto! He agendado tu cita para {conversation.selected_time} "
                        f"en {OFFICE_LOCATIONS[selected_office]}.\n\n"
                        f"Te espero ese día. Si necesitas reagendar o tienes alguna duda, escríbeme."
                    )

                    # Crear evento en Google Calendar
                    try:
                        calendar = CalendarClient()

                        # Parsear el datetime seleccionado
                        slot_dt = datetime.fromisoformat(conversation.proposed_times[0]["datetime"])
                        end_dt = slot_dt + timedelta(hours=1)

                        # Crear payload en formato Google Calendar API
                        event_payload = {
                            "summary": f"Consulta - {incoming}",
                            "start": {
                                "dateTime": slot_dt.isoformat(),
                                "timeZone": settings.scheduler_timezone
                            },
                            "end": {
                                "dateTime": end_dt.isoformat(),
                                "timeZone": settings.scheduler_timezone
                            },
                            "location": OFFICE_LOCATIONS[selected_office],
                            "description": f"Paciente: {incoming}\nSíntomas: {conversation.symptoms or 'No especificados'}",
                        }

                        await calendar.create_event(event_payload)
                        state.log_event("appointment.created", f"patient={incoming} time={conversation.selected_time} office={selected_office}")

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
                else:
                    response_text = "No entendí bien. ¿En cuál consultorio prefieres tu cita?\n- Muguerza\n- Zambrano\n- IMSS"
                    await gateway.send_message(
                        OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                    )
                    state.add_message_to_history(incoming, "assistant", response_text)
                    return {"status": "waiting_office_selection"}

            # Estado: eligiendo horario
            elif conversation.state == "scheduling":
                # Buscar si el usuario seleccionó un número
                selected_index = None
                for i in range(1, min(6, len(conversation.proposed_times) + 1)):
                    if str(i) in text:
                        selected_index = i - 1
                        break

                if selected_index is not None and selected_index < len(conversation.proposed_times):
                    selected_slot = conversation.proposed_times[selected_index]
                    conversation.selected_time = selected_slot["display"]
                    # Mover el slot seleccionado al principio para facilitar acceso después
                    conversation.proposed_times.insert(0, selected_slot)
                    conversation.state = "choosing_office"
                    state.set_appointment_conversation(incoming, conversation)

                    response_text = (
                        f"Excelente! Entonces te veo {selected_slot['display']}.\n\n"
                        f"¿En cuál consultorio prefieres tu cita?\n"
                        f"1. Hospital Muguerza Alta Especialidad\n"
                        f"2. Hospital Zambrano Hellion\n"
                        f"3. IMSS"
                    )

                    await gateway.send_message(
                        OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                    )

                    state.add_message_to_history(incoming, "assistant", response_text)
                    return {"status": "waiting_office_selection"}
                else:
                    response_text = "No entendí bien. Por favor elige el número de la opción que prefieres (1, 2, 3, etc.)"
                    await gateway.send_message(
                        OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                    )
                    state.add_message_to_history(incoming, "assistant", response_text)
                    return {"status": "waiting_time_selection"}

        # No hay conversación activa o está en estado inicial - analizar como consulta de salud normal
        analysis = await ai.analyze_health_query(message.text, conversation_history=history)

        is_emergency = analysis.get("is_emergency", False)
        needs_appointment = analysis.get("needs_appointment", False)
        needs_more_info = analysis.get("needs_more_info", False)
        suggested_response = analysis.get("suggested_response", "Entiendo tu consulta. ¿Cómo puedo ayudarte?")
        urgency = analysis.get("urgency", "low")

        state.log_event(
            "health.analysis",
            f"from={incoming} emergency={is_emergency} needs_appt={needs_appointment} urgency={urgency}",
        )

        response_text = suggested_response

        # Si es emergencia, solo loguear
        if is_emergency:
            state.log_event("health.emergency", f"from={incoming} message={message.text[:50]}")

        # Si el análisis sugiere que necesita cita O el usuario está preguntando explícitamente por horarios
        appointment_keywords = ["horario", "disponible", "cita", "agendar", "consulta", "mañana", "hoy", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo", "puedes"]
        is_asking_schedule = any(word in text for word in appointment_keywords)

        print(f"[DETECCIÓN CITA] patient={incoming} needs_appt={needs_appointment} needs_info={needs_more_info} is_asking={is_asking_schedule} keywords={[w for w in appointment_keywords if w in text]}")
        state.log_event("appointment.detection", f"patient={incoming} needs_appt={needs_appointment} needs_info={needs_more_info} is_asking={is_asking_schedule}")

        if (needs_appointment and not needs_more_info) or is_asking_schedule:
            # El usuario quiere agendar - revisar disponibilidad
            print(f"[CITA EN PROCESO] ✓ Iniciando revisión de disponibilidad para patient={incoming}")
            try:
                print(f"[CITA EN PROCESO] → Creando CalendarClient...")
                state.log_event("calendar.check_start", f"patient={incoming}")
                calendar = CalendarClient()
                print(f"[CITA EN PROCESO] ✓ CalendarClient creado, service={'OK' if calendar.service else 'NULL'}")
                state.log_event("calendar.client_created", f"patient={incoming} service={calendar.service is not None}")

                # Obtener eventos existentes para los próximos 7 días
                print(f"[CITA EN PROCESO] → Configurando zona horaria: {settings.scheduler_timezone}")
                tz = ZoneInfo(settings.scheduler_timezone)
                now = datetime.now(tz)
                start_date = now
                end_date = now + timedelta(days=7)

                print(f"[CITA EN PROCESO] → Consultando eventos desde {start_date.isoformat()} hasta {end_date.isoformat()}")
                state.log_event("calendar.list_events_start", f"patient={incoming} start={start_date.isoformat()} end={end_date.isoformat()}")
                existing_events = await calendar.list_events(start_date, end_date)
                print(f"[CITA EN PROCESO] ✓ Eventos obtenidos: {len(existing_events)} eventos encontrados")
                state.log_event("calendar.list_events_success", f"patient={incoming} events_count={len(existing_events)}")

                # Obtener slots disponibles
                print(f"[CITA EN PROCESO] → Calculando slots disponibles...")
                available_slots = await ai.suggest_available_slots(
                    existing_events,
                    settings.scheduler_timezone,
                    days_ahead=7
                )
                print(f"[CITA EN PROCESO] ✓ Slots disponibles: {len(available_slots)} slots encontrados")

                if available_slots:
                    print(f"[CITA EN PROCESO] → Creando conversación de agendamiento con {len(available_slots[:5])} opciones")
                    # Crear conversación de agendamiento
                    conversation = AppointmentConversation(
                        patient_number=incoming,
                        state="scheduling",
                        symptoms=message.text[:200],
                        proposed_times=available_slots[:5],  # Máximo 5 opciones
                    )
                    state.set_appointment_conversation(incoming, conversation)

                    # Construir mensaje con opciones
                    options_text = "Tengo disponibilidad en los siguientes horarios:\n\n"
                    for idx, slot in enumerate(available_slots[:5], 1):
                        options_text += f"{idx}. {slot['display']}\n"
                    options_text += "\n¿Cuál te acomoda mejor? (responde con el número)"

                    # Si suggested_response ya incluye info de cita, no duplicar
                    if "disponib" in suggested_response.lower() or "horario" in suggested_response.lower():
                        response_text = options_text
                    else:
                        response_text = suggested_response + "\n\n" + options_text

                    print(f"[CITA EN PROCESO] ✓ Ofreciendo {len(available_slots[:5])} horarios al paciente")
                    state.log_event("appointment.slots_offered", f"patient={incoming} count={len(available_slots[:5])}")
                else:
                    print(f"[CITA EN PROCESO] ✗ No hay slots disponibles")
                    response_text = "Déjame revisar mi agenda... Actualmente no tengo horarios disponibles en los próximos días. ¿Podrías llamarme directamente para coordinar?"
                    state.log_event("appointment.no_slots", f"patient={incoming}")

            except Exception as exc:
                import traceback
                error_detail = traceback.format_exc()
                print(f"[CITA EN PROCESO] ✗✗✗ ERROR ✗✗✗")
                print(f"[CITA EN PROCESO] Error tipo: {type(exc).__name__}")
                print(f"[CITA EN PROCESO] Error mensaje: {str(exc)}")
                print(f"[CITA EN PROCESO] Traceback completo:")
                print(error_detail)
                state.log_event("calendar.error", f"patient={incoming} error_type={type(exc).__name__} error_msg={str(exc)}")
                state.log_event("calendar.error_traceback", f"{error_detail}")
                response_text = "Disculpa, dame un momento para revisar mi agenda. Si es urgente, puedes llamarme directamente."

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
