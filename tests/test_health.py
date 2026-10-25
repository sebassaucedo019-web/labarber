from unittest.mock import MagicMock

from app import health


def test_readiness_checks_both_services_with_bounded_redis_timeout(monkeypatch):
    connection = MagicMock()
    factory = MagicMock(return_value=connection)
    session = MagicMock()
    monkeypatch.setattr(health.Redis, "from_url", factory)
    monkeypatch.setattr(health, "get_session", lambda: session)
    assert health.readiness() == {"status": "ok"}
    assert factory.call_args.kwargs["socket_timeout"] == 2
    connection.__enter__.return_value.ping.assert_called_once()
    session.__enter__.return_value.execute.assert_called_once()


def test_readiness_reports_outage_without_exposing_details(monkeypatch):
    monkeypatch.setattr(health.Redis, "from_url", MagicMock(side_effect=RuntimeError("secret")))
    response = health.readiness()
    assert response.status_code == 503
    assert b"secret" not in response.body
    assert health.health() == {"status": "ok"}
