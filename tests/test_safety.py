from app.safety import contains_banned_language, sanitize_reply


def test_sanitize_reply_keeps_mexican_tone() -> None:
    result = sanitize_reply("Qué onda, ahorita reviso tu cita.")
    assert "Qué onda" in result
    assert "ahorita" in result


def test_sanitize_reply_removes_common_insults() -> None:
    result = sanitize_reply("Ese pendejo es un cabrón")
    assert "pendejo" not in result.lower()
    assert "cabrón" not in result.lower()


def test_sanitize_reply_removes_more_insults_and_never_returns_empty() -> None:
    result = sanitize_reply("Eres un idiota, no mames")
    assert "idiota" not in result.lower()
    assert "no mames" not in result.lower()
    assert result


def test_detects_banned_language() -> None:
    assert contains_banned_language("No vale verga")
    assert not contains_banned_language("Quiero agendar una cita")
