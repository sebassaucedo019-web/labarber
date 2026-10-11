from app.safety import sanitize_reply


def test_sanitize_reply_keeps_mexican_tone() -> None:
    result = sanitize_reply("Qué onda, ahorita reviso tu cita.")
    assert "Qué onda" in result
    assert "ahorita" in result


def test_sanitize_reply_removes_common_insults() -> None:
    result = sanitize_reply("Ese pendejo es un cabrón")
    assert "pendejo" not in result.lower()
    assert "cabrón" not in result.lower()
