from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


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

    def set_pending(self, user_number: str, action: PendingEmailAction):
        self.pending_by_user[user_number] = action

    def get_pending(self, user_number: str) -> Optional[PendingEmailAction]:
        return self.pending_by_user.get(user_number)

    def clear_pending(self, user_number: str):
        if user_number in self.pending_by_user:
            del self.pending_by_user[user_number]


state = InMemoryState()
