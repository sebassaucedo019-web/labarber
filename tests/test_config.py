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


@pytest.mark.parametrize(
    "name", ["META_APP_SECRET", "OPENAI_API_KEY", "DATABASE_URL", "WHATSAPP_ACCESS_TOKEN"]
)
def test_required_variables_cannot_be_blank(monkeypatch, name):
    monkeypatch.setenv(name, "   ")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize("scheme", ["postgres", "postgresql"])
def test_railway_database_url_uses_psycopg3(monkeypatch, scheme):
    monkeypatch.setenv("DATABASE_URL", f"{scheme}://user:pass@db:5432/barber?sslmode=require")
    get_settings.cache_clear()
    assert (
        get_settings().database_url
        == "postgresql+psycopg://user:pass@db:5432/barber?sslmode=require"
    )
