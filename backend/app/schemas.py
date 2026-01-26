from pydantic import BaseModel


class IncomingWhatsAppMessage(BaseModel):
    from_number: str
    text: str
    timestamp: str | None = None


class OutgoingWhatsAppMessage(BaseModel):
    to_number: str
    text: str


class CalendarEventDraft(BaseModel):
    title: str
    start: str
    end: str | None = None
    location: str | None = None
    attendees: list[str] = []
    notes: str | None = None
