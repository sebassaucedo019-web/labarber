from unittest.mock import Mock

import httpx
import pytest

from app import escalation, sender
from app.config import get_settings
from app.observability import hash_wa_id

WA_ID = "526141111111"
REASON = "Quiero hablar con una persona"


def test_off_topic_message_is_not_a_real_escalation() -> None:
    assert escalation._REAL_ESCALATION_RE.search("El clima de hoy") is None
    assert escalation._REAL_ESCALATION_RE.search("Ayúdame con mi tarea") is None
    assert escalation._REAL_ESCALATION_RE.search("Gente pendeja") is None


def test_real_support_requests_are_escalated() -> None:
    assert escalation._REAL_ESCALATION_RE.search("Quiero hablar con una persona")
    assert escalation._REAL_ESCALATION_RE.search("Tengo un problema con mi cita")


def configure_owner(monkeypatch):
    monkeypatch.setenv("OWNER_WA_ID", "6140000000")
    get_settings.cache_clear()


def test_pending_notice_is_not_reported_as_already_sent(fake_redis, monkeypatch):
    configure_owner(monkeypatch)
    fake_redis.set(f"escalated:{hash_wa_id(WA_ID)}", "pending:interrupted", ex=60)
    delivery = Mock()
    monkeypatch.setattr(sender, "send_text", delivery)
    assert escalation.notify_human(WA_ID, REASON) is False
    delivery.assert_not_called()


def test_concurrent_notice_cannot_claim_success_before_delivery(fake_redis, monkeypatch):
    configure_owner(monkeypatch)

    def deliver(*args):
        assert escalation.notify_human(WA_ID, REASON) is False
        return True

    delivery = Mock(side_effect=deliver)
    monkeypatch.setattr(sender, "send_text", delivery)
    assert escalation.notify_human(WA_ID, REASON) is True
    assert fake_redis.get(f"escalated:{hash_wa_id(WA_ID)}") == "sent"
    assert escalation.notify_human(WA_ID, REASON) is True
    delivery.assert_called_once()


def test_failed_notice_releases_dedupe_and_can_be_retried(fake_redis, monkeypatch):
    configure_owner(monkeypatch)
    delivery = Mock(side_effect=[False, True])
    monkeypatch.setattr(sender, "send_text", delivery)
    assert escalation.notify_human(WA_ID, REASON) is False
    assert not fake_redis.exists(f"escalated:{hash_wa_id(WA_ID)}")
    assert escalation.notify_human(WA_ID, REASON) is True
    assert delivery.call_count == 2


def test_notice_deduplicates_legacy_and_canonical_numbers(fake_redis, monkeypatch):
    configure_owner(monkeypatch)
    delivery = Mock(return_value=True)
    monkeypatch.setattr(sender, "send_text", delivery)
    assert escalation.notify_human("5216141111111", REASON) is True
    assert escalation.notify_human(WA_ID, REASON) is True
    delivery.assert_called_once()


@pytest.mark.parametrize("accepted", [True, False])
def test_expired_notice_cannot_change_replacement_marker(fake_redis, monkeypatch, accepted):
    configure_owner(monkeypatch)
    key = f"escalated:{hash_wa_id(WA_ID)}"

    def deliver(*args):
        fake_redis.set(key, "pending:replacement", ex=60)
        return accepted

    monkeypatch.setattr(sender, "send_text", deliver)
    assert escalation.notify_human(WA_ID, REASON) is accepted
    assert fake_redis.get(key) == "pending:replacement"


def test_successful_notice_is_not_negated_by_bookkeeping_failure(fake_redis, monkeypatch):
    configure_owner(monkeypatch)
    monkeypatch.setattr(sender, "send_text", Mock(return_value=True))
    monkeypatch.setattr(escalation, "_finish_notice", Mock(side_effect=RuntimeError("redis")))
    assert escalation.notify_human(WA_ID, REASON) is True


@pytest.mark.parametrize("whatsapp_ok", [True, False])
def test_notice_records_actual_delivery_when_optional_webhook_fails(
    fake_redis, monkeypatch, whatsapp_ok
):
    configure_owner(monkeypatch)
    monkeypatch.setenv("ESCALATION_WEBHOOK_URL", "https://example.invalid/hook")
    get_settings.cache_clear()
    monkeypatch.setattr(sender, "send_text", Mock(return_value=whatsapp_ok))
    monkeypatch.setattr(escalation.httpx, "post", Mock(side_effect=httpx.ConnectError("offline")))
    assert escalation.notify_human(WA_ID, REASON) is whatsapp_ok
    marker = fake_redis.get(f"escalated:{hash_wa_id(WA_ID)}")
    assert marker == ("sent" if whatsapp_ok else None)
