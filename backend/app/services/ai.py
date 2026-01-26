from openai import AsyncOpenAI

from ..config import settings


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
