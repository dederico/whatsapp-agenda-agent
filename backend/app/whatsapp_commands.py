"""
Command parsing for WhatsApp messages.
All control is via WhatsApp in the MVP.
"""

from dataclasses import dataclass


@dataclass
class ParsedCommand:
    intent: str
    payload: dict


def parse_command(text: str) -> ParsedCommand:
    clean = (text or "").strip().lower()
    if clean in {"ignorar", "ignora", "ignore"}:
        return ParsedCommand(intent="ignore", payload={"raw": text})
    if clean in {"contestar", "responder", "responde"}:
        return ParsedCommand(intent="reply", payload={"raw": text})
    if clean in {"enviar", "manda", "mandar"}:
        return ParsedCommand(intent="send", payload={"raw": text})
    if clean in {"cancelar", "cancela"}:
        return ParsedCommand(intent="cancel", payload={"raw": text})
    if clean.startswith("resumen"):
        return ParsedCommand(intent="summary", payload={"raw": text})
    return ParsedCommand(intent="freeform", payload={"raw": text})
