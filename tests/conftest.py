import os

import fakeredis
import pytest

_TEST_ENV = {
    "META_APP_SECRET": "test-secret",
    "META_WEBHOOK_VERIFY_TOKEN": "test-verify-token",
    "WHATSAPP_PHONE_NUMBER_ID": "123456789",
    "WHATSAPP_ACCESS_TOKEN": "test-token",
    "OPENAI_API_KEY": "sk-test",
    "OPENAI_MODEL": "gpt-4o-mini",
    "DATABASE_URL": "sqlite:///:memory:",
}


def pytest_configure(config: pytest.Config) -> None:
    """Fija env de prueba antes de importar el agente (evita leer un placeholder local)."""
    for key, value in _TEST_ENV.items():
        os.environ[key] = value


@pytest.fixture(autouse=True)
def _required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _TEST_ENV.items():
        monkeypatch.setenv(key, value)

    from app.config import get_settings

    get_settings.cache_clear()


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> fakeredis.FakeStrictRedis:
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr("app.store.redis_store._client", client)
    return client
