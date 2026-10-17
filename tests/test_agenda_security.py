from app.agenda import _verify_token


def test_malformed_agenda_tokens_are_rejected() -> None:
    assert _verify_token("not-base64.%") is None
    assert _verify_token(".") is None
    assert _verify_token("a.b.c") is None
