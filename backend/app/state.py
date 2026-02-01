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


@dataclass
class AppointmentConversation:
    """Trackea el estado de una conversación de agendamiento de cita."""
    patient_number: str
    state: str = "initial"  # initial | diagnosing | offering_appointment | choosing_office | scheduling | confirming
    symptoms: Optional[str] = None
    proposed_times: list = field(default_factory=list)  # Lista de horarios propuestos
    selected_time: Optional[str] = None
    selected_office: Optional[str] = None  # muguerza | zambrano | imss
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_updated: datetime = field(default_factory=datetime.utcnow)


class InMemoryState:
    def __init__(self):
        self.pending_by_user: Dict[str, PendingEmailAction] = {}
        self.appointment_conversations: Dict[str, AppointmentConversation] = {}
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

    # Métodos para gestionar conversaciones de citas
    def get_appointment_conversation(self, patient_number: str) -> Optional[AppointmentConversation]:
        return self.appointment_conversations.get(patient_number)

    def set_appointment_conversation(self, patient_number: str, conversation: AppointmentConversation):
        conversation.last_updated = datetime.utcnow()
        self.appointment_conversations[patient_number] = conversation

    def clear_appointment_conversation(self, patient_number: str):
        if patient_number in self.appointment_conversations:
            del self.appointment_conversations[patient_number]


state = InMemoryState()
