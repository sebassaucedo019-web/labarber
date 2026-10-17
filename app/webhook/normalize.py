from collections.abc import Iterator
from typing import Any, TypedDict

MAX_INBOUND_TEXT_LENGTH = 4000


class InboundText(TypedDict):
    wa_id: str
    message_id: str
    text: str


def extract_text_messages(payload: dict[str, Any]) -> Iterator[InboundText]:
    """Solo mensajes de texto. Para audio, ver examples/audio_transcripcion."""
    entries = payload.get("entry", [])
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for change in entry.get("changes", []):
            if not isinstance(change, dict):
                continue
            value = change.get("value", {})
            if not isinstance(value, dict):
                continue
            for message in value.get("messages", []):
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
                    text = reply.get("title") or reply.get("id") or ""
                else:
                    continue
                if not isinstance(text, str):
                    continue
                text = text.strip()[:MAX_INBOUND_TEXT_LENGTH]
                if not message.get("from") or not message.get("id") or not text:
                    continue
                yield InboundText(
                    wa_id=message["from"],
                    message_id=message["id"],
                    text=text,
                )
