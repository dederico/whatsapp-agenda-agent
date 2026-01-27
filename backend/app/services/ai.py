from openai import AsyncOpenAI
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..config import settings
from ..schemas import CalendarEventDraft


class AIClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self.model = model or settings.openai_model

    async def summarize_email(self, subject: str, body: str) -> str:
        prompt = (
            "Resume en 1 oración el correo más importante para el dueño del inbox. "
            "No inventes detalles."
        )
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Asunto: {subject}\n\nContenido: {body}"},
            ],
        )
        output = response.choices[0].message.content or ""
        return output.strip() or "Sin resumen."

    async def parse_event(self, text: str, timezone: str) -> CalendarEventDraft:
        prompt = (
            "Convierte el texto a un JSON con las llaves: "
            "title, start, end, location, attendees, notes. "
            "start y end deben ser ISO 8601 con zona horaria. "
            "Si no hay end, déjalo null. "
            "attendees es una lista de emails si aparecen. "
            "No inventes datos."
        )
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": f"Zona horaria: {timezone}\nTexto: {text}",
                },
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        if "title" not in data or "start" not in data:
            raise ValueError("missing_required_fields")
        draft = CalendarEventDraft(**data)
        if not draft.end:
            try:
                start_dt = datetime.fromisoformat(draft.start.replace("Z", "+00:00"))
                end_dt = start_dt + timedelta(minutes=60)
                draft.end = end_dt.isoformat()
            except Exception:
                pass
        return draft
