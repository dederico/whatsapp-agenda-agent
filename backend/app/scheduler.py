from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from .config import settings
from .routes.gmail import poll_and_notify

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
