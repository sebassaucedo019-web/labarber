from collections.abc import Iterator
from typing import Any, TypedDict

MAX_INBOUND_TEXT_LENGTH = 4000


class InboundText(TypedDict):
    wa_id: str
    message_id: str
    text: str


def extract_text_messages(
    payload: dict[str, Any], *, phone_number_id: str | None = None
) -> Iterator[InboundText]:
    """Solo mensajes de texto. Para audio, ver examples/audio_transcripcion."""
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        changes = entry.get("changes", [])
        if not isinstance(changes, list):
            continue
        for change in changes:
            if not isinstance(change, dict):
                continue
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue
            if phone_number_id:
                metadata = value.get("metadata")
                if (
                    not isinstance(metadata, dict)
                    or metadata.get("phone_number_id") != phone_number_id
                ):
                    continue
            messages = value.get("messages", [])
            if not isinstance(messages, list):
                continue
            for message in messages:
                if not isinstance(message, dict):
                    continue
                message_type = message.get("type")
                if message_type == "text":
                    text_data = message.get("text", {})
                    text = text_data.get("body", "") if isinstance(text_data, dict) else ""
                elif message_type == "interactive":
                    interactive = message.get("interactive", {})
                    if not isinstance(interactive, dict):
                        continue
                    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    if not isinstance(reply, dict):
                        continue
                    button_id = reply.get("id")
                    intents = {
                        "services": "Ver servicios",
                        "book": "Agendar cita",
                        "my_appointment": "Consultar mi cita",
                        "staff_agenda": "Dame el enlace de la agenda",
                        "staff_next": "Que cita sigue en la agenda",
                        "staff_cancel": "Quiero cancelar una cita de la agenda",
                    }
                    text = intents.get(button_id, "") if isinstance(button_id, str) else ""
                    text = text or reply.get("title") or ""
                else:
                    continue
                if not isinstance(text, str):
                    continue
                text = text.strip()[:MAX_INBOUND_TEXT_LENGTH]
                sender = message.get("from")
                message_id = message.get("id")
                if (
                    not isinstance(sender, str)
                    or not isinstance(message_id, str)
                    or not sender.strip()
                    or not message_id.strip()
                    or not text
                ):
                    continue
                yield InboundText(
                    wa_id=sender.strip(),
                    message_id=message_id.strip(),
                    text=text,
                )
