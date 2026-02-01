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

        # Obtener conversación existente si hay una
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

                        event_draft = CalendarEventDraft(
                            title=f"Consulta - {incoming}",
                            start=slot_dt.isoformat(),
                            end=end_dt.isoformat(),
                            location=OFFICE_LOCATIONS[selected_office],
                            notes=f"Paciente: {incoming}\nSíntomas: {conversation.symptoms or 'No especificados'}",
                        )

                        await calendar.create_event(event_draft)
                        state.log_event("appointment.created", f"patient={incoming} time={conversation.selected_time} office={selected_office}")

                        # Limpiar conversación
                        state.clear_appointment_conversation(incoming)
                    except Exception as exc:
                        state.log_event("appointment.error", f"patient={incoming} error={str(exc)}")
                        response_text += "\n\n(Nota: Hubo un problema al crear el evento en el calendario, pero tu cita está confirmada)"

                    await gateway.send_message(
                        OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                    )

                    return {"status": "appointment_confirmed"}
                else:
                    response_text = "No entendí bien. ¿En cuál consultorio prefieres tu cita?\n- Muguerza\n- Zambrano\n- IMSS"
                    await gateway.send_message(
                        OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                    )
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

                    return {"status": "waiting_office_selection"}
                else:
                    response_text = "No entendí bien. Por favor elige el número de la opción que prefieres (1, 2, 3, etc.)"
                    await gateway.send_message(
                        OutgoingWhatsAppMessage(to_number=message.from_number, text=response_text)
                    )
                    return {"status": "waiting_time_selection"}

        # No hay conversación activa o está en estado inicial - analizar como consulta de salud normal
        analysis = await ai.analyze_health_query(message.text)

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

        # Si el análisis sugiere que necesita cita Y no necesita más info
        if needs_appointment and not needs_more_info:
            # Verificar si el usuario está aceptando agendar
            if any(word in text for word in ["sí", "si", "dale", "okay", "ok", "claro", "agendar", "cita"]):
                try:
                    calendar = CalendarClient()

                    # Obtener eventos existentes para los próximos 7 días
                    tz = ZoneInfo(settings.timezone)
                    now = datetime.now(tz)
                    start_date = now.isoformat()
                    end_date = (now + timedelta(days=7)).isoformat()

                    existing_events = await calendar.list_events(start_date, end_date)

                    # Obtener slots disponibles
                    available_slots = await ai.suggest_available_slots(
                        existing_events,
                        settings.timezone,
                        days_ahead=7
                    )

                    if available_slots:
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

                        response_text = suggested_response + "\n\n" + options_text

                        state.log_event("appointment.slots_offered", f"patient={incoming} count={len(available_slots[:5])}")
                    else:
                        response_text += "\n\nActualmente no tengo horarios disponibles en los próximos días. ¿Podrías llamarme directamente para coordinar?"
                        state.log_event("appointment.no_slots", f"patient={incoming}")

                except Exception as exc:
                    state.log_event("calendar.error", f"patient={incoming} error={str(exc)}")
                    response_text += "\n\nDisculpa, tuve un problema al revisar la agenda. ¿Podrías llamarme directamente?"

        # Enviar respuesta
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=message.from_number,
                text=response_text,
            )
        )

        state.log_event("whatsapp.response_sent", f"to={incoming} emergency={is_emergency} appt={needs_appointment}")

        return {
            "status": "processed",
            "emergency": is_emergency,
            "needs_appointment": needs_appointment,
            "urgency": urgency,
        }

    except Exception as exc:
        state.log_event("whatsapp.error", f"from={incoming} error={str(exc)}")
        # En caso de error, enviar respuesta genérica
        try:
            await gateway.send_message(
                OutgoingWhatsAppMessage(
                    to_number=message.from_number,
                    text="Disculpa, estoy teniendo problemas técnicos. Por favor intenta de nuevo o llama al doctor directamente si es urgente.",
                )
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(exc))
