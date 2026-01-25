import httpx

from ..config import settings
from ..schemas import OutgoingWhatsAppMessage


class WhatsAppGateway:
    def __init__(self):
        self.base_url = settings.whatsapp_gateway_url
        self.api_key = settings.whatsapp_gateway_api_key

    async def send_message(self, message: OutgoingWhatsAppMessage):
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{self.base_url}/send",
                json=message.model_dump(),
                headers={"x-api-key": self.api_key},
                timeout=10,
            )
