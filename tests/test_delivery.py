import logging
from unittest.mock import Mock

import pytest

from app import notifications, sender
from app.observability import RedactAccessQuery


def test_legacy_notification_job_can_finish_after_upgrade(monkeypatch):
    delivery = Mock(return_value=False)
    monkeypatch.setattr(notifications, "send_text", delivery)
    with pytest.raises(RuntimeError, match="rechaz"):
        notifications.deliver_notification("526141111111", "Cita confirmada")
    delivery.return_value = True
    notifications.deliver_notification("526141111111", "Cita confirmada")
    assert delivery.call_count == 2


def test_send_text_reports_meta_failure(monkeypatch):
    client = Mock()
    client.send_message.side_effect = RuntimeError("Meta unavailable")
    monkeypatch.setattr(sender, "get_client", lambda: client)
    assert sender.send_text("526141111111", "Mensaje") is False


def test_menu_fallback_reports_failure(monkeypatch):
    monkeypatch.setattr(sender.httpx, "post", Mock(side_effect=RuntimeError("Meta unavailable")))
    monkeypatch.setattr(sender, "send_text", Mock(return_value=False))
    assert sender.send_welcome_buttons("526141111111") is False
    sender.send_text.assert_called_once()


@pytest.mark.parametrize("path", ["/agenda?token=secret", "/webhook?hub.verify_token=secret"])
def test_access_log_hides_credentials(path):
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", path, "1.1", 200),
        None,
    )
    assert RedactAccessQuery().filter(record)
    assert "secret" not in record.getMessage()
    assert path.split("?")[0] in record.getMessage()
