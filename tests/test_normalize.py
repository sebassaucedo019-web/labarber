from app.webhook.normalize import extract_text_messages


def test_normalize_accepts_text_and_interactive_replies() -> None:
    payload = {
        "entry": [{
            "changes": [{
                "value": {"messages": [
                    {"from": "5216143649949", "id": "wamid.text", "type": "text", "text": {"body": " hola "}},
                    {"from": "5216143649949", "id": "wamid.button", "type": "interactive", "interactive": {"button_reply": {"id": "book", "title": "Agendar cita"}}},
                ]}
            }]
        }]
    }

    assert list(extract_text_messages(payload)) == [
        {"wa_id": "5216143649949", "message_id": "wamid.text", "text": "hola"},
        {"wa_id": "5216143649949", "message_id": "wamid.button", "text": "Agendar cita"},
    ]


def test_normalize_ignores_malformed_messages_and_limits_text() -> None:
    long_text = "x" * 5000
    payload = {
        "entry": [{
            "changes": [{"value": {"messages": [
                {"from": 5216, "id": "bad", "type": "text", "text": {"body": "no"}},
                {"from": "5216", "id": "", "type": "text", "text": {"body": "no"}},
                {"from": "5216", "id": "long", "type": "text", "text": {"body": long_text}},
            ]}}]
        }]
    }

    messages = list(extract_text_messages(payload))
    assert len(messages) == 1
    assert len(messages[0]["text"]) == 4000
