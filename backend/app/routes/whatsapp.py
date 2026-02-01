from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..config import settings
from ..schemas import IncomingWhatsAppMessage, OutgoingWhatsAppMessage
from ..services.whatsapp_gateway import WhatsAppGateway
from ..services.calendar import CalendarClient
from ..services.ai import AIClient
from ..state import state

router = APIRouter()
gateway = WhatsAppGateway()


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

    # IMPORTANTE: Ahora aceptamos mensajes de CUALQUIER número (bot público)
    # No verificamos si es el owner, respondemos a todos

    try:
        ai = AIClient(settings.openai_api_key)

        # Analizar el mensaje como consulta de salud
        analysis = await ai.analyze_health_query(message.text)

        is_emergency = analysis.get("is_emergency", False)
        needs_appointment = analysis.get("needs_appointment", False)
        suggested_response = analysis.get("suggested_response", "Entiendo tu consulta. ¿Cómo puedo ayudarte?")
        urgency = analysis.get("urgency", "low")

        state.log_event(
            "health.analysis",
            f"from={incoming} emergency={is_emergency} needs_appt={needs_appointment} urgency={urgency}",
        )

        # Construir respuesta
        response_text = suggested_response

        # Si es emergencia, agregar mensaje urgente de llamar al doctor
        if is_emergency:
            response_text += "\n\n🚨 Por favor, llama AHORA al doctor o acude a emergencias de inmediato. Este es un asunto urgente que requiere atención médica profesional."
            state.log_event("health.emergency", f"from={incoming} message={message.text[:50]}")

        # Si necesita cita (pero no es emergencia), intentar crear cita automáticamente
        if needs_appointment and not is_emergency:
            try:
                # Crear cita para "mañana a las 10am" por defecto
                tz = ZoneInfo(settings.scheduler_timezone)
                now = datetime.now(tz)
                tomorrow_10am = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
                end_time = tomorrow_10am + timedelta(hours=1)

                cal = CalendarClient()
                event_payload = {
                    "summary": f"Cita médica - {incoming[-4:]}",
                    "description": f"Paciente con consulta: {message.text[:100]}",
                    "start": {"dateTime": tomorrow_10am.isoformat()},
                    "end": {"dateTime": end_time.isoformat()},
                }
                created = await cal.create_event(event_payload)

                response_text += f"\n\n📅 He agendado una cita para mañana a las 10:00 AM. El doctor te contactará pronto."
                state.log_event(
                    "calendar.auto_create",
                    f"from={incoming} event={created.get('id')} time={tomorrow_10am.isoformat()}",
                )
            except Exception as exc:
                state.log_event("calendar.auto_create_failed", f"from={incoming} error={str(exc)}")
                response_text += "\n\nTe recomiendo agendar una cita con el doctor pronto."

        # Enviar respuesta automáticamente
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
