from openai import AsyncOpenAI
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List

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
            "agenda, create_event, cancel_event, reply, send, ignore, cancel, chat. "
            "Devuelve JSON con llaves: intent, rationale (breve). "
            "Si el usuario pide agenda, usa agenda. "
            "Si quiere crear una cita, usa create_event. "
            "Si quiere cancelar una cita, usa cancel_event. "
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
        if data.get("intent") not in {"agenda", "create_event", "cancel_event", "reply", "send", "ignore", "cancel", "chat"}:
            data["intent"] = "chat"
        return data

    async def analyze_health_query(self, text: str, conversation_history: list = None) -> dict:
        """Analiza consulta de salud y determina urgencia y necesidad de cita."""
        prompt = (
            "Eres el Dr. Eduardo González Dávila, neo-neonatólogo de Monterrey con más de 10 años de experiencia. "
            "Analiza este mensaje en el contexto de la conversación y devuelve JSON con: "
            "is_emergency (bool): true si es emergencia médica que requiere atención inmediata, "
            "needs_appointment (bool): true si el paciente está preguntando por horarios o pidiendo cita, "
            "needs_more_info (bool): true si necesitas hacer preguntas para entender mejor el caso, "
            "urgency (str): 'high', 'medium', 'low', "
            "suggested_response (str): respuesta cálida, empática y profesional. "
            "IMPORTANTE: SOLO preséntate si es el PRIMER mensaje del historial (no hay mensajes previos). "
            "Si ya hay historial, NO repitas tu presentación. "
            "Haz preguntas diagnósticas cuando sea necesario. "
            "Da tips y recomendaciones básicas cuando sea apropiado. "
            "Conduce sutilmente hacia agendar cita, pero de manera natural y no agresiva. "
            "Si es emergencia, recomienda FIRMEMENTE acudir a emergencias de inmediato."
        )

        # Construir mensajes con historial
        messages = [{"role": "system", "content": prompt}]

        # Agregar historial si existe
        if conversation_history:
            for msg in conversation_history:
                messages.append({"role": msg["role"], "content": msg["content"]})

        # Agregar mensaje actual
        messages.append({"role": "user", "content": text})

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {
                "is_emergency": False,
                "needs_appointment": False,
                "urgency": "low",
                "suggested_response": "Entiendo tu consulta. ¿Puedes darme más detalles?",
            }
        return data

    async def chat_response(self, text: str) -> str:
        """Respuesta como Dr. Eduardo González Dávila."""
        prompt = (
            "Eres el Dr. Eduardo González Dávila, neo-neonatólogo de Monterrey, Nuevo León. "
            "Tienes más de 10 años de experiencia, más de 20 certificaciones, y te mantienes en constante actualización profesional. "
            "Hiciste tu servicio social en Reynosa, Tamaulipas. Eres padre de dos niñas (Sofia y Paulina) y esposo de Tere Garza. "
            "\n\n"
            "INSTRUCCIONES:\n"
            "- Si es el PRIMER mensaje, preséntate: 'Hola! Soy el Dr. Eduardo González Dávila, será un gusto atenderte.'\n"
            "- Haz preguntas para entender mejor (¿hace cuánto?, ¿qué tan intenso?, ¿síntomas adicionales?)\n"
            "- Da tips y recomendaciones básicas (remedios caseros, medicamentos de venta libre, cuidados)\n"
            "- Conduce SUTILMENTE a que agenden cita CONTIGO en tu consultorio\n"
            "- NUNCA digas 'consulta a un médico' - TÚ ERES EL MÉDICO\n"
            "- Di cosas como: '¿Te gustaría que te revise en consultorio?', 'Podemos agendar una cita para revisarte'\n"
            "- Si es emergencia GRAVE (peligro de vida), recomienda ir a urgencias PERO ofrece seguimiento contigo después\n"
            "- NO des diagnósticos definitivos, solo orientación\n"
            "- Sé breve (máximo 3-4 párrafos cortos), cálido y profesional"
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

    async def suggest_available_slots(
        self,
        existing_events: List[dict],
        timezone: str,
        days_ahead: int = 7
    ) -> List[dict]:
        """
        Analiza eventos existentes y sugiere horarios disponibles.
        Retorna lista de slots disponibles con formato amigable.
        """
        tz = ZoneInfo(timezone)
        now = datetime.now(tz)

        # Horario de consultorio: Lunes a Domingo, 8am-6pm
        # Slots de 1 hora cada uno
        available_slots = []

        for day_offset in range(days_ahead):
            day = now + timedelta(days=day_offset + 1)  # Empezar desde mañana

            # Horario: Todos los días 8am-6pm
            start_hour, end_hour = 8, 18  # 8am-6pm

            # Revisar cada hora
            for hour in range(start_hour, end_hour):
                slot_start = day.replace(hour=hour, minute=0, second=0, microsecond=0)
                slot_end = slot_start + timedelta(hours=1)

                # Verificar si hay conflicto con eventos existentes
                has_conflict = False
                for event in existing_events:
                    event_start_str = event.get("start", {}).get("dateTime")
                    event_end_str = event.get("end", {}).get("dateTime")

                    if event_start_str and event_end_str:
                        try:
                            event_start = datetime.fromisoformat(event_start_str.replace("Z", "+00:00"))
                            event_end = datetime.fromisoformat(event_end_str.replace("Z", "+00:00"))

                            # Hay conflicto si los slots se solapan
                            if slot_start < event_end and slot_end > event_start:
                                has_conflict = True
                                break
                        except Exception:
                            continue

                if not has_conflict:
                    # Formatear para el usuario
                    day_name = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"][day.weekday()]
                    available_slots.append({
                        "datetime": slot_start.isoformat(),
                        "display": f"{day_name} {day.day} de {slot_start.strftime('%B')} a las {hour}:00",
                        "day": day_name,
                        "date": day.strftime("%Y-%m-%d"),
                        "time": f"{hour}:00"
                    })

        return available_slots[:10]  # Retornar máximo 10 slots
