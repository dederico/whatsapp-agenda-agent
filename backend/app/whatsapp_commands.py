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
    if clean in {"ignorar", "ignora", "ignore"} or "ignorar" in clean or "ignora" in clean:
        return ParsedCommand(intent="ignore", payload={"raw": text})
    if clean in {"contestar", "responder", "responde"} or "contestar" in clean or "responder" in clean:
        return ParsedCommand(intent="reply", payload={"raw": text})
    if clean in {"enviar", "manda", "mandar"} or "enviar" in clean or "manda" in clean:
        return ParsedCommand(intent="send", payload={"raw": text})
    if clean in {"si", "sí", "ok", "dale", "va", "enviar", "envia", "envíalo"}:
        return ParsedCommand(intent="confirm", payload={"raw": text})
    if clean in {"no", "nel", "nope", "no enviar", "no lo envíes", "no lo envies"}:
        return ParsedCommand(intent="reject", payload={"raw": text})
    if clean in {"agenda", "próximos", "proximos", "calendario"}:
        return ParsedCommand(intent="agenda", payload={"raw": text})
    if clean.startswith("crear evento"):
        return ParsedCommand(intent="create_event", payload={"raw": text})
    if clean.startswith("cancelar evento") or clean.startswith("cancela evento"):
        return ParsedCommand(intent="cancel_event", payload={"raw": text})
    if "correo" in clean and ("escribir" in clean or "escribirme" in clean):
        return ParsedCommand(intent="help_email", payload={"raw": text})
    if clean in {"cancelar", "cancela"}:
        return ParsedCommand(intent="cancel", payload={"raw": text})
    if clean.startswith("resumen"):
        return ParsedCommand(intent="summary", payload={"raw": text})
    return ParsedCommand(intent="freeform", payload={"raw": text})
