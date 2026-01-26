from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from ..services.calendar import CalendarClient

router = APIRouter()


@router.get("/calendar/next")
async def calendar_next():
    cal = CalendarClient()
    try:
        now = datetime.utcnow()
        events = await cal.list_events(now, now + timedelta(days=1), max_results=10)
    except RuntimeError:
        raise HTTPException(status_code=400, detail="calendar_not_authorized")
    return {"events": events}
