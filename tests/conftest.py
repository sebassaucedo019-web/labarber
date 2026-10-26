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
    "OWNER_WA_ID": "",
    "BARBER_OBED_WA_ID": "",
    "BARBER_JESUS_WA_ID": "",
    "BARBER_YADIER_WA_ID": "",
    "ESCALATION_WEBHOOK_URL": "",
    "PUBLIC_BASE_URL": "https://labarber-production-b9de.up.railway.app",
}


def pytest_configure(config: pytest.Config) -> None:
    """Fija env de prueba antes de importar el agente (evita leer un placeholder local)."""
    for key, value in _TEST_ENV.items():
        os.environ[key] = value


@pytest.fixture(scope="session", autouse=True)
def _close_worker_loop():
    yield
    from app.queue.tasks import close_async_runner

    close_async_runner()


@pytest.fixture(autouse=True)
def _required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in _TEST_ENV.items():
        monkeypatch.setenv(key, value)

    from app.config import get_settings

    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _no_live_http(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from pydantic_ai import models

    def blocked(*args, **kwargs):
        raise AssertionError("Las pruebas no deben hacer llamadas HTTP reales")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", blocked)
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> fakeredis.FakeStrictRedis:
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr("app.store.redis_store._client", client)
    return client
