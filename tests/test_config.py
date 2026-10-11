import pytest
from pydantic import ValidationError

from app.config import get_settings


def test_openai_model_rejects_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
    get_settings.cache_clear()


def test_openai_model_accepts_configured_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "gpt-6-luna")
    get_settings.cache_clear()
    assert get_settings().openai_model == "gpt-6-luna"
    get_settings.cache_clear()


def test_openai_model_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_MODEL", "  gpt-4o-mini  ")
    get_settings.cache_clear()
    assert get_settings().openai_model == "gpt-4o-mini"
    get_settings.cache_clear()
