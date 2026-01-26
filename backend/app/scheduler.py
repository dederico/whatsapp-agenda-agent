from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import settings
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .routes.gmail import poll_and_notify
from .schemas import OutgoingWhatsAppMessage
from .services.calendar import CalendarClient
from .services.whatsapp_gateway import WhatsAppGateway
from .state import state

scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)


def start_scheduler():
    if scheduler.running:
        return
    scheduler.start()


def schedule_gmail_poll(minutes: int | None = None):
    interval = minutes or settings.gmail_poll_minutes
    scheduler.add_job(
        poll_and_notify,
        IntervalTrigger(minutes=interval),
        id="gmail_poll",
        replace_existing=True,
    )


async def check_calendar_reminders():
    cal = CalendarClient()
    now = datetime.now(ZoneInfo(settings.scheduler_timezone))
    horizon = now + timedelta(hours=24)
    events = await cal.list_events(now, horizon, max_results=20)
    gateway = WhatsAppGateway()
    offsets = [1440, 60, 10]
    label = {1440: "24h", 60: "1h", 10: "10 min"}
    for ev in events:
        start = ev.get("start", {}).get("dateTime")
        if not start:
            continue
        try:
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(
                ZoneInfo(settings.scheduler_timezone)
            )
        except Exception:
            continue
        delta_minutes = int((start_dt - now).total_seconds() / 60)
        for offset in offsets:
            if abs(delta_minutes - offset) <= 1:
                key = f"{ev.get('id')}:{offset}"
                if key in state.reminders_sent:
                    continue
                summary = ev.get("summary", "(sin título)")
                location = ev.get("location")
                attendees = ev.get("attendees", [])
                who = ", ".join([a.get("email", "") for a in attendees if a.get("email")])
                when = start_dt.strftime("%Y-%m-%d %H:%M")
                extra = f" con {who}" if who else ""
                place = f" en {location}" if location else ""
                text = (
                    f"Recordatorio: en {label.get(offset, f'{offset} min')} "
                    f"tienes {summary}{extra}{place} a las {when}."
                )
                await gateway.send_message(
                    OutgoingWhatsAppMessage(
                        to_number=settings.owner_whatsapp_number, text=text
                    )
                )
                state.mark_reminder_sent(key)
                state.log_event("calendar.reminder", text)


async def send_gap_recommendations():
    now = datetime.now(ZoneInfo(settings.scheduler_timezone))
    today = now.date().isoformat()
    if state.last_reco_date == today:
        return
    cal = CalendarClient()
    start_day = datetime.combine(now.date(), datetime.min.time(), tzinfo=ZoneInfo(settings.scheduler_timezone))
    end_day = start_day + timedelta(hours=23, minutes=59)
    events = await cal.list_events(start_day, end_day, max_results=50)
    starts = []
    for ev in events:
        s = ev.get("start", {}).get("dateTime")
        if not s:
            continue
        try:
            starts.append(datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(ZoneInfo(settings.scheduler_timezone)))
        except Exception:
            continue
    starts.sort()
    # Find a 2h gap after now
    gap_start = now
    for s in starts:
        if s <= now:
            gap_start = max(gap_start, s)
            continue
        if (s - gap_start).total_seconds() >= 7200:
            gap_end = s
            break
        gap_start = s
    else:
        gap_end = None
    if gap_end:
        pending_count = len(state.pending_by_user)
        pending_note = f" Tienes {pending_count} pendientes." if pending_count else ""
        text = (
            f"Tienes un hueco de 2h entre {gap_start.strftime('%H:%M')} y {gap_end.strftime('%H:%M')}."
            f"{pending_note} ¿Quieres agendar algo?"
        )
        gateway = WhatsAppGateway()
        await gateway.send_message(
            OutgoingWhatsAppMessage(
                to_number=settings.owner_whatsapp_number, text=text
            )
        )
        state.log_event("calendar.reco", text)
    state.last_reco_date = today


def schedule_calendar_checks():
    scheduler.add_job(
        check_calendar_reminders,
        IntervalTrigger(minutes=1),
        id="calendar_reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        send_gap_recommendations,
        IntervalTrigger(minutes=60),
        id="calendar_recos",
        replace_existing=True,
    )
