from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional
from collections import deque


@dataclass
class PendingEmailAction:
    action_id: str
    sender: str
    subject: str
    summary: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    status: str = "pending"  # pending | drafting | approved | ignored
    draft_reply: Optional[str] = None


class InMemoryState:
    def __init__(self):
        self.pending_by_user: Dict[str, PendingEmailAction] = {}
        self.events = deque(maxlen=200)
        self.reminders_sent: set[str] = set()
        self.last_reco_date: str | None = None
        self.seen_email_ids: set[str] = set()

    def set_pending(self, user_number: str, action: PendingEmailAction):
        self.pending_by_user[user_number] = action

    def get_pending(self, user_number: str) -> Optional[PendingEmailAction]:
        return self.pending_by_user.get(user_number)

    def clear_pending(self, user_number: str):
        if user_number in self.pending_by_user:
            del self.pending_by_user[user_number]

    def log_event(self, kind: str, detail: str):
        self.events.appendleft(
            {
                "ts": datetime.utcnow().isoformat(),
                "kind": kind,
                "detail": detail,
            }
        )

    def mark_reminder_sent(self, key: str):
        if len(self.reminders_sent) > 2000:
            self.reminders_sent.clear()
        self.reminders_sent.add(key)

    def mark_email_seen(self, message_id: str):
        if len(self.seen_email_ids) > 5000:
            self.seen_email_ids.clear()
        self.seen_email_ids.add(message_id)

    def has_seen_email(self, message_id: str) -> bool:
        return message_id in self.seen_email_ids


state = InMemoryState()
