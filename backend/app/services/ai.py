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

    async def classify_intent(self, text: str, has_pending: bool, pending_summary: str | None) -> dict:
        prompt = (
            "Eres un router de intents para WhatsApp. Elige SOLO un intent: "
            "agenda, create_event, reply, send, ignore, cancel, chat. "
            "Devuelve JSON con llaves: intent, rationale (breve). "
            "Si el usuario pide agenda, usa agenda. "
            "Si quiere crear una cita, usa create_event. "
            "Si quiere contestar correo, usa reply. "
            "Si confirma enviar, usa send. "
            "Si quiere ignorar/eliminar, usa ignore. "
            "Si quiere cancelar, usa cancel. "
            "Si es charla normal, usa chat."
        )
        context = {
            "has_pending_email": has_pending,
            "pending_summary": pending_summary or "",
        }
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Contexto: {json.dumps(context)}\nTexto: {text}"},
            ],
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"intent": "chat", "rationale": "parse_error"}
        if data.get("intent") not in {"agenda", "create_event", "reply", "send", "ignore", "cancel", "chat"}:
            data["intent"] = "chat"
        return data

    async def chat_response(self, text: str) -> str:
        prompt = (
            "Responde de forma humana y amigable. "
            "Sé breve y útil. Si no sabes, pregunta por más detalle."
        )
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
        )
        output = response.choices[0].message.content or ""
        return output.strip() or "Ok."

    async def parse_event(self, text: str, timezone: str) -> CalendarEventDraft:
        prompt = (
            "Convierte el texto a un JSON con las llaves: "
            "title, start, end, location, attendees, notes. "
            "start y end deben ser ISO 8601 con zona horaria. "
            "Si no hay end, déjalo null. "
            "attendees es una lista de emails si aparecen. "
            "No inventes datos."
        )
        now_iso = datetime.now(ZoneInfo(timezone)).isoformat()
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": f"{prompt}\nFecha/hora actual: {now_iso}\nZona horaria: {timezone}",
                },
                {
                    "role": "user",
                    "content": f"Texto: {text}",
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
