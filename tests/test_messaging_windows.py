from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import appointment_template, messaging_window, notifications
from app.config import get_settings
from app.store.models import Appointment, Base, CustomerWindow, NotificationOutbox

RECIPIENT = "526143649949"


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'window.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(messaging_window, "get_session", factory)
    monkeypatch.setattr(notifications, "get_session", factory)
    yield factory
    engine.dispose()


def payload(at, phone="123456789"):
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone},
                            "messages": [
                                {
                                    "id": "wamid.a",
                                    "from": "5216143649949",
                                    "type": "text",
                                    "text": {"body": "Hola"},
                                    "timestamp": str(int(at.replace(tzinfo=UTC).timestamp())),
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_window_uses_provider_time_and_does_not_extend_on_replay(database):
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    recent = now - timedelta(hours=1)
    messaging_window.process_customer_windows(payload(recent))
    messaging_window.process_customer_windows(payload(now - timedelta(days=2)))
    messaging_window.process_customer_windows(payload(now, "another-number"))
    messaging_window.process_customer_windows(payload(now + timedelta(hours=1)))
    with database() as db:
        assert db.get(CustomerWindow, RECIPIENT).last_message_at == recent
    assert messaging_window.window_is_open(RECIPIENT, now)
    assert not messaging_window.window_is_open(RECIPIENT, recent + timedelta(hours=24))
    assert not messaging_window.window_is_open("525500000000", now)


@pytest.mark.parametrize("template_status", ["sent", "failed", "uncertain"])
def test_closed_window_uses_template_only(database, monkeypatch, template_status):
    with database() as db:
        row = Appointment(
            wa_id=RECIPIENT,
            customer_name="Ana",
            service="corte normal",
            starts_at=datetime(2090, 1, 2, 12),
            barber="Obed",
        )
        db.add(row)
        db.flush()
        notifications.notify(
            RECIPIENT, "Cita confirmada", session=db, appointment_id=row.id, event_id="abc"
        )
        db.commit()
    freeform = Mock(side_effect=AssertionError("No freeform outside window"))
    template = Mock(return_value=(template_status, None if template_status == "sent" else "reason"))
    monkeypatch.setattr(notifications, "send_text", freeform)
    monkeypatch.setattr(notifications, "send_appointment_template", template)
    assert notifications.dispatch_pending() == 1
    assert notifications.dispatch_pending() == 0
    template.assert_called_once_with(RECIPIENT, "Cita confirmada")
    freeform.assert_not_called()
    with database() as db:
        assert db.scalar(select(NotificationOutbox)).status == template_status


def test_unconfigured_template_makes_no_network_call():
    assert appointment_template.send_appointment_template(RECIPIENT, "Cita") == (
        "failed",
        "appointment_template_not_configured",
    )


def test_expired_template_submission_lease_is_not_retried(database):
    now = datetime.now(UTC).replace(tzinfo=None)
    with database() as db:
        appointment = Appointment(
            wa_id=RECIPIENT,
            customer_name="Ana",
            service="corte normal",
            starts_at=datetime(2090, 1, 2, 12),
            barber="Obed",
        )
        db.add(appointment)
        db.flush()
        db.add(
            NotificationOutbox(
                appointment_id=appointment.id,
                recipient=RECIPIENT,
                message="Aviso",
                event_id="interrupted",
                status="sending",
                available_at=now - timedelta(seconds=1),
                attempts=1,
                lease_token="lost",
                last_error="template_submitting",
            )
        )
        db.commit()
    assert notifications.claim_notification() is None
    with database() as db:
        row = db.scalar(select(NotificationOutbox))
        assert row.status == "uncertain" and row.lease_token is None


def test_support_outside_window_requires_its_own_template(fake_redis, monkeypatch):
    from app import escalation, sender

    monkeypatch.setenv("OWNER_WA_ID", "525500000001")
    get_settings.cache_clear()
    monkeypatch.setattr(escalation, "window_is_open", lambda *args: False)
    freeform = Mock(side_effect=AssertionError("No freeform outside window"))
    monkeypatch.setattr(sender, "send_text", freeform)
    assert escalation.notify_human(RECIPIENT, "Quiero hablar con una persona") == "failed"
    freeform.assert_not_called()
    template = Mock(return_value=("uncertain", "unknown"))
    monkeypatch.setattr(escalation, "send_appointment_template", template)
    assert escalation.notify_human(RECIPIENT, "Quiero hablar con una persona") == "pending"
    assert escalation.notify_human(RECIPIENT, "Quiero hablar con una persona") == "pending"
    template.assert_called_once()


@pytest.mark.parametrize(
    "http_status,expected", [(200, "sent"), (400, "failed"), (429, "pending"), (503, "uncertain")]
)
def test_template_payload_and_errors(monkeypatch, http_status, expected):
    monkeypatch.setenv("APPOINTMENT_TEMPLATE_NAME", "actualizacion_cita")
    get_settings.cache_clear()
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.post.return_value = httpx.Response(http_status, json={"messages": [{"id": "test-id"}]})
    monkeypatch.setattr(appointment_template.httpx, "Client", lambda **kwargs: client)
    state, _ = appointment_template.send_appointment_template(
        RECIPIENT, "Cita confirmada\nAna 12:00"
    )
    assert state == expected
    data = client.post.call_args.kwargs["json"]
    assert data["type"] == "template"
    assert data["template"]["components"][0]["parameters"][0]["text"] == "Cita confirmada Ana 12:00"
