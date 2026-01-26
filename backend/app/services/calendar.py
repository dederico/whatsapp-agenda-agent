from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .google_auth import get_calendar_service
from ..config import settings


def _to_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(settings.scheduler_timezone))
    return dt.isoformat()


def _parse_dt(value: str) -> datetime:
    if value.endswith("Z"):
        value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


class CalendarClient:
    def __init__(self):
        self.service = get_calendar_service()

    def _ensure_service(self):
        if not self.service:
            raise RuntimeError("Calendar not authorized")

    async def list_events(self, start: datetime, end: datetime, max_results: int = 10):
        self._ensure_service()
        resp = (
            self.service.events()
            .list(
                calendarId=settings.google_calendar_id,
                timeMin=_to_rfc3339(start),
                timeMax=_to_rfc3339(end),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return resp.get("items", [])

    async def create_event(self, payload: dict):
        self._ensure_service()
        return (
            self.service.events()
            .insert(calendarId=settings.google_calendar_id, body=payload)
            .execute()
        )

    @staticmethod
    def event_start_end(event: dict) -> tuple[datetime | None, datetime | None]:
        start = event.get("start", {})
        end = event.get("end", {})
        if "dateTime" in start:
            start_dt = _parse_dt(start["dateTime"])
        elif "date" in start:
            start_dt = datetime.fromisoformat(start["date"])
        else:
            start_dt = None
        if "dateTime" in end:
            end_dt = _parse_dt(end["dateTime"])
        elif "date" in end:
            end_dt = datetime.fromisoformat(end["date"]) + timedelta(days=1)
        else:
            end_dt = None
        return start_dt, end_dt
