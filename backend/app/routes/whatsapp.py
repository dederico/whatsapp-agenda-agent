from fastapi import APIRouter, HTTPException

from ..config import settings
from ..schemas import IncomingWhatsAppMessage, OutgoingWhatsAppMessage
from ..services.whatsapp_gateway import WhatsAppGateway
from ..services.gmail import GmailClient
from ..state import state
from ..whatsapp_commands import parse_command

router = APIRouter()
gateway = WhatsAppGateway()


@router.post("/whatsapp/incoming")
async def whatsapp_incoming(message: IncomingWhatsAppMessage):
    if message.from_number != settings.owner_whatsapp_number:
        raise HTTPException(status_code=403, detail="unauthorized")

    command = parse_command(message.text)
    pending = state.get_pending(message.from_number)

    if command.intent == "ignore":
        if not pending:
            return {"status": "no_pending"}
        pending.status = "ignored"
        GmailClient().archive_message(pending.action_id)
        state.clear_pending(message.from_number)
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=message.from_number,
                text="Listo, archivé el correo.",
            )
        )
        return {"status": "ignored"}

    if command.intent == "reply":
        if not pending:
            return {"status": "no_pending"}
        pending.status = "drafting"
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=message.from_number,
                text="Perfecto. Dicta tu respuesta breve y yo preparo el borrador.",
            )
        )
        return {"status": "drafting"}

    if command.intent == "send":
        if not pending or not pending.draft_reply:
            return {"status": "no_draft"}
        pending.status = "approved"
        GmailClient().send_reply(pending.sender, f"Re: {pending.subject}", pending.draft_reply)
        state.clear_pending(message.from_number)
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=message.from_number,
                text="Enviado. Si quieres agregar seguimiento, dímelo.",
            )
        )
        return {"status": "sent"}

    if command.intent == "cancel":
        if not pending:
            return {"status": "no_pending"}
        state.clear_pending(message.from_number)
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=message.from_number,
                text="Cancelado. No enviaré respuesta.",
            )
        )
        return {"status": "cancelled"}

    if pending and pending.status == "drafting":
        pending.draft_reply = message.text.strip()
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=message.from_number,
                text=(
                    "Tengo este borrador:\n\n"
                    f"{pending.draft_reply}\n\n"
                    "¿Lo envío?"
                ),
            )
        )
        return {"status": "draft_ready"}

    return {"status": "ok"}
