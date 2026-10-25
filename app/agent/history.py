"""Trim whole turns so tool results never outlive their tool calls."""

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    SystemPromptPart,
    TextPart,
    UserPromptPart,
)


def trim_history(messages: list[ModelMessage], limit: int = 24) -> list[ModelMessage]:
    # Old stored system prompts included yesterday's date and superseded rules.
    cleaned = []
    for message in messages:
        if isinstance(message, ModelRequest):
            message.parts = [
                part for part in message.parts if not isinstance(part, SystemPromptPart)
            ]
            if not message.parts:
                continue
        cleaned.append(message)
    start = max(0, len(cleaned) - limit)
    while start < len(cleaned):
        message = cleaned[start]
        if isinstance(message, ModelRequest) and any(
            isinstance(p, UserPromptPart) for p in message.parts
        ):
            return cleaned[start:]
        start += 1
    return []


def conversational_context(messages: list[ModelMessage]) -> str:
    parts = []
    for message in messages[-8:]:
        for part in message.parts:
            if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                parts.append("Cliente: " + part.content[:1000])
            elif isinstance(part, TextPart):
                parts.append("Asistente: " + part.content[:1000])
    return "\n".join(parts)[-4000:]
