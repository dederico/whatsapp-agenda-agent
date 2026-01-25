import base64
from email.message import EmailMessage

from .google_auth import get_gmail_service


class GmailClient:
    def __init__(self):
        self.service = get_gmail_service()

    def _ensure_service(self):
        if not self.service:
            raise RuntimeError("Gmail not authorized")

    def list_unread(self, max_results: int = 5):
        self._ensure_service()
        resp = (
            self.service.users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=max_results)
            .execute()
        )
        return resp.get("messages", [])

    def get_message(self, message_id: str):
        self._ensure_service()
        msg = (
            self.service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        return msg

    def archive_message(self, message_id: str):
        self._ensure_service()
        self.service.users().messages().modify(
            userId="me",
            id=message_id,
            body={"removeLabelIds": ["INBOX", "UNREAD"]},
        ).execute()

    def delete_message(self, message_id: str):
        self._ensure_service()
        self.service.users().messages().delete(userId="me", id=message_id).execute()

    def send_reply(self, to_email: str, subject: str, body: str):
        self._ensure_service()
        message = EmailMessage()
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)
        encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
        self.service.users().messages().send(userId="me", body={"raw": encoded}).execute()


def extract_headers(payload: dict) -> dict:
    headers = payload.get("headers", [])
    result = {}
    for h in headers:
        name = h.get("name", "").lower()
        value = h.get("value", "")
        if name in {"from", "subject"}:
            result[name] = value
    return result


def extract_snippet(message: dict) -> str:
    return message.get("snippet", "")
