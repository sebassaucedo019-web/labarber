from collections.abc import Iterator
from typing import Any, TypedDict


class InboundText(TypedDict):
    wa_id: str
    message_id: str
    text: str


def extract_text_messages(payload: dict[str, Any]) -> Iterator[InboundText]:
    """Solo mensajes de texto. Para audio, ver examples/audio_transcripcion."""
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for message in value.get("messages", []):
                message_type = message.get("type")
                if message_type == "text":
                    text = message.get("text", {}).get("body", "")
                elif message_type == "interactive":
                    interactive = message.get("interactive", {})
                    reply = interactive.get("button_reply") or interactive.get("list_reply") or {}
                    text = reply.get("title") or reply.get("id") or ""
                else:
                    continue
                if not message.get("from") or not message.get("id") or not text.strip():
                    continue
                yield InboundText(
                    wa_id=message["from"],
                    message_id=message["id"],
                    text=text,
                )
