from pydantic import BaseModel


class IncomingWhatsAppMessage(BaseModel):
    from_number: str
    text: str
    timestamp: str | None = None


class OutgoingWhatsAppMessage(BaseModel):
    to_number: str
    text: str
