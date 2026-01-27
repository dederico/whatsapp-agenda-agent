from fastapi import APIRouter, HTTPException
from datetime import datetime, timedelta
import re

from ..config import settings
from ..schemas import IncomingWhatsAppMessage, OutgoingWhatsAppMessage
from ..services.whatsapp_gateway import WhatsAppGateway
from ..services.gmail import GmailClient
from ..services.calendar import CalendarClient
from ..services.ai import AIClient
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
    state.log_event(
        "whatsapp.command",
        f"intent={command.intent} pending={pending.status if pending else 'none'} text={message.text}",
    )

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

    if command.intent == "agenda":
        cal = CalendarClient()
        now = datetime.utcnow()
        end = now + timedelta(days=1)
        events = await cal.list_events(now, end, max_results=5)
        if not events:
            await gateway.send_message(
                OutgoingWhatsAppMessage(
                    to_number=settings.owner_whatsapp_number,
                    text="No tienes eventos próximos en 24h.",
                )
            )
            return {"status": "no_events"}
        lines = []
        for ev in events:
            summary = ev.get("summary", "(sin título)")
            start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
            location = ev.get("location")
            when = start or "sin hora"
            extra = f" · {location}" if location else ""
            lines.append(f"- {summary} · {when}{extra}")
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number,
                text="Próximos eventos:\n" + "\n".join(lines),
            )
        )
        return {"status": "events_sent"}

    if command.intent == "create_event":
        raw = command.payload.get("raw", "")
        ai = AIClient(settings.openai_api_key)
        draft = None
        # Fast-path: if ISO datetime is present, parse locally.
        match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw)
        if match:
            start_iso = match.group(0)
            title = raw
            title = re.sub(r"(?i)^crear evento\s*", "", title)
            title = title.replace(start_iso, "").strip()
            if not title:
                title = "Evento"
            draft = CalendarEventDraft(title=title, start=start_iso)
        if not draft:
            try:
                draft = await ai.parse_event(raw, settings.scheduler_timezone)
            except ValueError:
                await gateway.send_message(
                    OutgoingWhatsAppMessage(
                        to_number=settings.owner_whatsapp_number,
                        text=(
                            "No pude entender el evento. Ejemplos:\n"
                            "1) crear evento mañana 6am llamado LEVANTARSE en casa\n"
                            "2) crear evento LEVANTARSE 2026-01-27T06:00:00-06:00"
                        ),
                    )
                )
                return {"status": "parse_failed"}
        payload = {
            "summary": draft.title,
            "location": draft.location,
            "description": draft.notes,
            "start": {"dateTime": draft.start},
            "end": {"dateTime": draft.end or draft.start},
        }
        if draft.attendees:
            payload["attendees"] = [{"email": a} for a in draft.attendees]
        cal = CalendarClient()
        created = await cal.create_event(payload)
        state.log_event("calendar.create", f"{created.get('summary')} @ {created.get('start')}")
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number,
                text=f"Listo, agendé: {created.get('summary')}.",
            )
        )
        return {"status": "created"}

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
