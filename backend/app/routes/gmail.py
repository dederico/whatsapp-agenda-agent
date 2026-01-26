from fastapi import APIRouter, HTTPException

from ..config import settings
from ..services.ai import AIClient
from ..services.gmail import GmailClient, extract_headers, extract_snippet
from ..services.whatsapp_gateway import WhatsAppGateway
from ..state import PendingEmailAction, state
from ..schemas import OutgoingWhatsAppMessage

router = APIRouter()
gateway = WhatsAppGateway()

def _normalize_number(raw: str) -> str:
    # Strip non-digits and normalize MX mobile (52/521) prefixes.
    digits = "".join(ch for ch in (raw or "") if ch.isdigit())
    if digits.startswith("521"):
        return "52" + digits[3:]
    return digits


async def poll_and_notify():
    gmail = GmailClient()
    messages = gmail.list_unread(max_results=1)
    if not messages:
        return {"status": "no_unread"}

    msg_id = messages[0]["id"]
    full = gmail.get_message(msg_id)
    headers = extract_headers(full.get("payload", {}))
    sender = headers.get("from", "desconocido")
    subject = headers.get("subject", "(sin asunto)")
    snippet = extract_snippet(full)

    ai = AIClient(settings.openai_api_key)
    summary = await ai.summarize_email(subject, snippet)

    pending = PendingEmailAction(
        action_id=msg_id,
        sender=sender,
        subject=subject,
        summary=summary,
    )
    state.set_pending(_normalize_number(settings.owner_whatsapp_number), pending)
    state.log_event("email.new", f"From {sender} - {subject}")

    await gateway.send_message(
        OutgoingWhatsAppMessage(
            to_number=settings.owner_whatsapp_number,
            text=(
                f"Jefe, recibiste un correo de {sender}. "
                f"Dice lo siguiente: {summary}.\n\n"
                "¿Quieres ignorarlo o contestar?"
            ),
        )
    )
    return {"status": "notified", "message_id": msg_id}


@router.post("/gmail/poll")
async def gmail_poll():
    try:
        return await poll_and_notify()
    except RuntimeError:
        raise HTTPException(status_code=400, detail="gmail_not_authorized")
