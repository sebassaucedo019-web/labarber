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
                if message.get("type") != "text":
                    continue
                yield InboundText(
                    wa_id=message["from"],
                    message_id=message["id"],
                    text=message.get("text", {}).get("body", ""),
                )
