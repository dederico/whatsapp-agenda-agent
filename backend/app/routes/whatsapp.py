from fastapi import APIRouter, HTTPException

from ..config import settings
from ..schemas import IncomingWhatsAppMessage, OutgoingWhatsAppMessage
from ..services.whatsapp_gateway import WhatsAppGateway
from ..services.gmail import GmailClient
from ..state import state
from ..whatsapp_commands import parse_command

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
    owner = _normalize_number(settings.owner_whatsapp_number)
    incoming = _normalize_number(message.from_number)
    state.log_event("whatsapp.incoming", f"from={message.from_number} norm={incoming}")
    is_lid = len(incoming) > 13
    if not owner or (incoming != owner and not is_lid):
        state.log_event(
            "whatsapp.unauthorized",
            f"from={message.from_number} norm={incoming} owner={owner}",
        )
        raise HTTPException(status_code=403, detail="unauthorized")
    if incoming != owner and is_lid:
        state.log_event(
            "whatsapp.lid",
            f"from={message.from_number} norm={incoming} owner={owner}",
        )

    command = parse_command(message.text)
    user_key = owner
    pending = state.get_pending(user_key)

    if command.intent == "ignore":
        if not pending:
            return {"status": "no_pending"}
        pending.status = "ignored"
        GmailClient().archive_message(pending.action_id)
        state.clear_pending(user_key)
        state.log_event("email.ignore", f"Archived email {pending.action_id}")
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number,
                text="Listo, archivé el correo.",
            )
        )
        return {"status": "ignored"}

    if command.intent == "reply":
        if not pending:
            return {"status": "no_pending"}
        pending.status = "drafting"
        state.log_event("email.reply.start", f"Drafting reply to {pending.sender}")
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number,
                text="Perfecto. Dicta tu respuesta breve y yo preparo el borrador.",
            )
        )
        return {"status": "drafting"}

    if command.intent == "send":
        if not pending or not pending.draft_reply:
            return {"status": "no_draft"}
        pending.status = "approved"
        GmailClient().send_reply(pending.sender, f"Re: {pending.subject}", pending.draft_reply)
        state.clear_pending(user_key)
        state.log_event("email.sent", f"Sent reply to {pending.sender}")
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number,
                text="Enviado. Si quieres agregar seguimiento, dímelo.",
            )
        )
        return {"status": "sent"}

    if command.intent == "confirm":
        if not pending or not pending.draft_reply:
            return {"status": "no_draft"}
        pending.status = "approved"
        GmailClient().send_reply(pending.sender, f"Re: {pending.subject}", pending.draft_reply)
        state.clear_pending(user_key)
        state.log_event("email.sent", f"Sent reply to {pending.sender}")
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number,
                text="Enviado. Si quieres agregar seguimiento, dímelo.",
            )
        )
        return {"status": "sent"}

    if command.intent == "reject":
        if not pending:
            return {"status": "no_pending"}
        pending.status = "drafting"
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number,
                text="Ok, dicta la nueva respuesta y preparo el borrador.",
            )
        )
        return {"status": "drafting"}

    if command.intent == "cancel":
        if not pending:
            return {"status": "no_pending"}
        state.clear_pending(user_key)
        state.log_event("email.cancel", "Cancelled pending reply")
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number,
                text="Cancelado. No enviaré respuesta.",
            )
        )
        return {"status": "cancelled"}

    if pending and pending.status == "drafting":
        pending.draft_reply = message.text.strip()
        pending.status = "draft_ready"
        state.log_event("email.draft", "Draft prepared")
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number,
                text=(
                    "Tengo este borrador:\n\n"
                    f"{pending.draft_reply}\n\n"
                    "¿Lo envío?"
                ),
            )
        )
        return {"status": "draft_ready"}

    return {"status": "ok"}
