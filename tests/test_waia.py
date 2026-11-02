import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app import notifications, panel, panel_auth, reminders, scheduling, staff
from app.agent import tools
from app.agent.deps import BotDeps
from app.config import get_settings
from app.main import app
from app.store.models import (
    Appointment,
    AppointmentEvent,
    Base,
    MessagingPreference,
    NotificationOutbox,
    StaffAccount,
    StaffSession,
)
from app.webhook import receipts

NOW = datetime(2026, 11, 1, 12)
OWNER, OBED, JESUS, CLIENT = "526141111111", "526142222222", "526143333333", "526144444444"
ORIGIN = "https://testserver"
PASSWORD = "Synthetic-test-pass-678"
REAL_TEMPLATE_SENDER = reminders.send_template_notice


@pytest.fixture
def db(tmp_path, monkeypatch, fake_redis):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'waia.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    for module in (panel, panel_auth, reminders, notifications, receipts):
        monkeypatch.setattr(module, "get_session", factory)
    for module in (panel, reminders, scheduling):
        monkeypatch.setattr(module, "local_now", lambda: NOW)
    monkeypatch.setattr(tools, "_now", lambda: NOW)
    monkeypatch.setattr(tools, "confirm_action", lambda *args: True)
    monkeypatch.setattr(notifications, "send_text", Mock(return_value=True))
    monkeypatch.setattr(
        reminders, "send_template_notice", Mock(return_value=("sent", "wamid.test", None))
    )
    for key, value in {
        "OWNER_WA_ID": OWNER,
        "BARBER_OBED_WA_ID": OBED,
        "BARBER_JESUS_WA_ID": JESUS,
        "PUBLIC_BASE_URL": ORIGIN,
        "AUTOMATIC_NOTICES_ENABLED": "false",
        "BARBERS": "[]",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield factory
    engine.dispose()
    get_settings.cache_clear()


def appointment(session, offset=15, barber="Obed", status="confirmed", consent=True, **kwargs):
    row = Appointment(
        wa_id=CLIENT,
        customer_name="Cliente Simulado",
        service="corte normal",
        barber=barber,
        starts_at=NOW + timedelta(minutes=offset),
        status=status,
        reminder_consent=consent,
        **kwargs,
    )
    session.add(row)
    session.flush()
    return row


def enable(monkeypatch):
    monkeypatch.setenv("AUTOMATIC_NOTICES_ENABLED", "true")
    get_settings.cache_clear()


def complete(factory, identity, scope="Obed"):
    with factory() as session:
        row = scheduling.transition(session, identity, scope, "test-staff", "completed")
        session.commit()
        return row


@pytest.mark.parametrize(
    "offset,status,consent,count",
    [
        (15, "confirmed", True, 1),
        (180, "confirmed", True, 0),
        (15, "arrived", True, 0),
        (15, "cancelled", True, 0),
        (15, "completed", True, 0),
        (15, "confirmed", False, 0),
        (-5, "confirmed", True, 0),
        (0, "confirmed", True, 1),
    ],
)
def test_finish_notifies_only_eligible_next_appointment(db, offset, status, consent, count):
    with db() as session:
        current = appointment(session, -30, status="in_service")
        following = appointment(session, offset, status=status, consent=consent)
        session.commit()
    complete(db, current.id)
    with db() as session:
        assert session.get(Appointment, current.id).completed_at == NOW
        rows = session.scalars(select(NotificationOutbox)).all()
        assert len(rows) == count
        if rows:
            assert rows[0].appointment_id == following.id and rows[0].kind == "next_turn"
            assert rows[0].scheduled_start == following.starts_at


def test_do_not_skip_present_or_overdue_next_customer_to_notify_another(db):
    for status in ("arrived", "in_service"):
        with db() as session:
            session.query(NotificationOutbox).delete()
            session.query(AppointmentEvent).delete()
            session.query(Appointment).delete()
            current = appointment(session, -30, status="in_service")
            appointment(session, 10, status=status)
            appointment(session, 20)
            session.commit()
        complete(db, current.id)
        with db() as session:
            assert session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0


def test_repeated_complete_and_simultaneous_barbers_are_idempotent(db):
    with db() as session:
        a = appointment(session, -30, "Obed", "in_service")
        b = appointment(session, -30, "Jesús", "in_service")
        a_next = appointment(session, 15, "Obed")
        b_next = appointment(session, 20, "Jesús")
        session.commit()
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [
            pool.submit(complete, db, a.id),
            pool.submit(complete, db, a.id),
            pool.submit(complete, db, b.id, "Jesús"),
        ]
        for future in futures:
            future.result()
    with db() as session:
        notices = session.scalars(select(NotificationOutbox)).all()
        assert {n.appointment_id for n in notices} == {a_next.id, b_next.id} and len(notices) == 2
        assert session.scalar(select(func.count()).select_from(AppointmentEvent)) == 2


def test_wrong_barber_cannot_modify_or_create_event(db):
    with db() as session:
        row = appointment(session, -30, "Jesús")
        session.commit()
    with pytest.raises(PermissionError):
        complete(db, row.id)
    with db() as session:
        assert session.get(Appointment, row.id).status == "confirmed"
        assert session.scalar(select(AppointmentEvent)) is None


def test_arrival_is_reversible_but_terminal_states_are_not(db):
    with db() as session:
        row = appointment(session)
        reminders.stage_notice(session, row, "reminder", NOW)
        session.commit()
        scheduling.transition(session, row.id, "Obed", "staff", "arrived")
        session.commit()
        assert row.arrived_at == NOW and row.starts_at == NOW + timedelta(minutes=15)
        assert session.scalar(select(NotificationOutbox)).status == "cancelled"
        scheduling.transition(session, row.id, "Obed", "staff", "confirmed")
        session.commit()
        assert row.arrived_at is None
        with pytest.raises(ValueError):
            scheduling.transition(session, row.id, "Obed", "staff", "completed")


def test_no_show_requires_grace_and_preserves_reserved_slot(db):
    with db() as session:
        row = appointment(session, -5)
        session.commit()
        with pytest.raises(ValueError):
            scheduling.transition(session, row.id, "Obed", "staff", "no_show")
        scheduling.transition(
            session, row.id, "Obed", "staff", "no_show", NOW + timedelta(minutes=15)
        )
        session.commit()
        with pytest.raises(ValueError):
            scheduling.transition(session, row.id, "Obed", "staff", "arrived")
        assert not scheduling.available(session, "Obed", row.starts_at)


def test_new_automatic_messages_disabled_but_existing_outbox_not_blocked(db):
    with db() as session:
        row = appointment(session)
        reminders.stage_notice(session, row, "reminder", NOW)
        notifications.notify(
            CLIENT, "Cambio confirmado", session=session, appointment_id=row.id, event_id="old-flow"
        )
        session.commit()
    assert notifications.dispatch_pending() == 1
    reminders.send_template_notice.assert_not_called()
    notifications.send_text.assert_called_once()


def test_whatsapp_failure_preserves_completed_state_and_retries(db, monkeypatch):
    enable(monkeypatch)
    with db() as session:
        row = appointment(session, -30, status="in_service")
        appointment(session)
        session.commit()
    complete(db, row.id)
    reminders.send_template_notice.return_value = ("pending", None, "meta_http_503")
    assert notifications.dispatch_pending() == 1
    assert notifications.dispatch_pending() == 0
    with db() as session:
        assert session.get(Appointment, row.id).status == "completed"
        notice = session.scalar(select(NotificationOutbox))
        assert notice.status == "pending" and notice.attempts == 1
        notice.available_at = datetime(2000, 1, 1)
        session.commit()
    reminders.send_template_notice.return_value = ("sent", "wamid.ok", None)
    assert notifications.dispatch_pending() == 1
    with db() as session:
        notice = session.scalar(select(NotificationOutbox))
        assert notice.status == "sent" and notice.accepted_at and notice.delivered_at is None


def test_unknown_submission_and_worker_crash_do_not_send_twice(db, monkeypatch):
    enable(monkeypatch)
    with db() as session:
        row = appointment(session)
        reminders.stage_notice(session, row, "reminder", NOW)
        session.commit()
    delivery = notifications.claim_notification()
    with db() as session:
        notice = session.get(NotificationOutbox, delivery.id)
        notice.available_at = datetime(2000, 1, 1)
        session.commit()
    assert notifications.claim_notification() is None
    with db() as session:
        assert session.get(NotificationOutbox, delivery.id).status == "uncertain"
    reminders.send_template_notice.assert_not_called()


def test_reminders_recover_after_restart_and_dedupe_next_turn(db):
    with db() as session:
        prior = appointment(session, -30, status="in_service")
        row = appointment(session, 30)
        session.commit()
    reminders.reconcile_reminders()
    reminders.reconcile_reminders()
    complete(db, prior.id)
    with db() as session:
        notices = session.scalars(select(NotificationOutbox)).all()
        assert len(notices) == 1 and notices[0].appointment_id == row.id


@pytest.mark.parametrize(
    "offset,changed,count", [(2, None, 0), (15, NOW, 0), (30, NOW, 1), (31, None, 0)]
)
def test_specific_rule_for_short_notice_and_late_reminders(db, offset, changed, count):
    with db() as session:
        appointment(session, offset, schedule_updated_at=changed)
        session.commit()
    reminders.reconcile_reminders()
    with db() as session:
        assert session.scalar(select(func.count()).select_from(NotificationOutbox)) == count


def test_reschedule_invalidates_old_notice_and_rebuilds_new(db, monkeypatch):
    with db() as session:
        appointment(session, 30)
        session.commit()
    reminders.reconcile_reminders()
    with db() as session:
        ctx = SimpleNamespace(deps=BotDeps(wa_id=CLIENT, db=session, user_message="Sí"))
        result = tools.reagendar_cita(ctx, "2026-11-01 12:30", "2026-11-01 13:00", "Jesús")
        assert "reagendada" in result
    reminders.reconcile_reminders(NOW + timedelta(minutes=30))
    with db() as session:
        notices = session.scalars(
            select(NotificationOutbox)
            .where(NotificationOutbox.kind == "reminder")
            .order_by(NotificationOutbox.id)
        ).all()
        assert len(notices) == 2 and notices[0].status == "cancelled"
        assert notices[1].scheduled_barber == "Jesús" and notices[1].scheduled_start.hour == 13


@pytest.mark.parametrize("change", ["cancelled", "arrived", "completed", "revoke"])
def test_delivery_rechecks_state_after_claim(db, monkeypatch, change):
    enable(monkeypatch)
    with db() as session:
        row = appointment(session)
        reminders.stage_notice(session, row, "reminder", NOW)
        session.commit()
    delivery = notifications.claim_notification()
    with db() as session:
        row = session.get(Appointment, row.id)
        if change == "revoke":
            row.reminder_consent = False
        else:
            row.status = change
        session.commit()
    reminders.dispatch_automatic(delivery)
    reminders.send_template_notice.assert_not_called()
    with db() as session:
        assert session.get(NotificationOutbox, delivery.id).status == "cancelled"


def payload(value):
    return {
        "entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "123456789"}, **value}}]}]
    }


def test_receipts_are_monotonic_and_never_fake_delivery(db, monkeypatch):
    enable(monkeypatch)
    with db() as session:
        row = appointment(session)
        n = reminders.stage_notice(session, row, "reminder", NOW)
        session.commit()
    notifications.dispatch_pending()
    receipt = {
        "id": "wamid.test",
        "recipient_id": CLIENT,
        "status": "delivered",
        "timestamp": str(int(datetime.now(UTC).timestamp())),
        "biz_opaque_callback_data": f"waia:{n.id}:{n.event_id}",
    }
    receipts.process_receipts(payload({"statuses": [{**receipt, "recipient_id": OWNER}]}))
    with db() as session:
        assert session.get(NotificationOutbox, n.id).status == "sent"
    for status in ("delivered", "sent", "read", "failed", "delivered"):
        receipts.process_receipts(payload({"statuses": [{**receipt, "status": status}]}))
    with db() as session:
        stored = session.get(NotificationOutbox, n.id)
        assert stored.status == "read" and stored.delivered_at and stored.read_at


def test_stop_revokes_all_aliases_and_new_consent_requires_explicit_resubscribe(db):
    with db() as session:
        row = appointment(session)
        reminders.stage_notice(session, row, "reminder", NOW)
        session.commit()
    receipts.process_opt_out(
        payload({"messages": [{"type": "text", "from": "5216144444444", "text": {"body": "STOP"}}]})
    )
    with db() as session:
        assert not session.get(Appointment, row.id).reminder_consent
        assert session.get(MessagingPreference, CLIENT).opted_out
        assert session.scalar(select(NotificationOutbox)).status == "cancelled"


def test_blocks_affect_existing_bot_booking_and_can_not_cover_booked_slots(db):
    with db() as session:
        scheduling.create_block(
            session,
            "all",
            "admin",
            "Obed",
            NOW + timedelta(hours=1),
            NOW + timedelta(hours=2),
            "Comida",
        )
        session.commit()
        ctx = SimpleNamespace(deps=BotDeps(wa_id=CLIENT, db=session, user_message="Sí"))
        assert "bloqueado" in tools.agendar(ctx, "2026-11-01 13:00", "corte normal", "Ana", "Obed")
        available = tools.consultar_disponibilidad(ctx, "2026-11-01", "Obed")
        assert "13:00" not in available and "14:00" in available
        appointment(session, 180)
        session.commit()
        with pytest.raises(ValueError):
            scheduling.create_block(
                session,
                "all",
                "admin",
                "Obed",
                NOW + timedelta(hours=3),
                NOW + timedelta(hours=4),
                "Comida",
            )


def test_reservation_index_covers_arrived_and_completed(db):
    with db() as session:
        row = appointment(session, 30, status="arrived")
        session.commit()
        with pytest.raises(IntegrityError):
            appointment(session, 30, status="confirmed")
        session.rollback()
        session.get(Appointment, row.id).status = "completed"
        session.commit()
        assert not scheduling.available(session, "Obed", row.starts_at)


@pytest.fixture
def browser(db):
    with db() as session:
        for username, phone in (("owner", OWNER), ("obed", OBED), ("jesus", JESUS)):
            session.add(
                StaffAccount(
                    username=username, wa_id=phone, password_hash=panel_auth.password_hash(PASSWORD)
                )
            )
        session.commit()
    client = TestClient(app, base_url=ORIGIN)
    yield client
    client.close()


def sign_in(client, username="obed"):
    response = client.post(
        "/api/agenda/login",
        json={"username": username, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 200, response.text
    assert (
        "Secure" in response.headers["set-cookie"] and "HttpOnly" in response.headers["set-cookie"]
    )
    csrf = client.get("/api/agenda/session").json()["csrf"]
    return {"Origin": ORIGIN, "X-CSRF-Token": csrf}


def test_login_roles_csrf_and_inaccessible_foreign_appointments(browser, db):
    assert browser.get("/api/agenda/calendar").status_code == 401
    with db() as session:
        own = appointment(session, -30)
        foreign = appointment(session, 30, "Jesús")
        session.commit()
    headers = sign_in(browser)
    calendar = browser.get("/api/agenda/calendar").json()
    assert {r["id"] for r in calendar["appointments"]} == {own.id}
    assert browser.get("/api/agenda/calendar?barber=Jesús").status_code == 403
    body = {"state": "completed", "expected_status": "confirmed"}
    assert (
        browser.post(
            f"/api/agenda/appointments/{foreign.id}/state", headers=headers, json=body
        ).status_code
        == 404
    )
    assert browser.post(f"/api/agenda/appointments/{own.id}/state", json=body).status_code == 403
    assert (
        browser.post(
            f"/api/agenda/appointments/{own.id}/state",
            headers={**headers, "Origin": "https://evil.test"},
            json=body,
        ).status_code
        == 403
    )
    assert (
        browser.post(
            f"/api/agenda/appointments/{own.id}/state", headers=headers, json=body
        ).status_code
        == 200
    )
    assert browser.get("/api/agenda/notifications").status_code == 403
    headers = sign_in(browser, "owner")
    assert len(browser.get("/api/agenda/calendar").json()["appointments"]) == 2
    assert browser.get("/api/agenda/notifications").status_code == 200
    assert browser.post("/api/agenda/logout", headers=headers).status_code == 200
    assert browser.get("/api/agenda/calendar").status_code == 401


def test_staff_removed_from_configuration_loses_existing_session(browser, monkeypatch):
    sign_in(browser)
    monkeypatch.setenv("BARBER_OBED_WA_ID", "")
    get_settings.cache_clear()
    assert browser.get("/api/agenda/calendar").status_code == 401


def test_login_rate_limit_and_session_revocation(browser, db):
    for _ in range(8):
        assert (
            browser.post(
                "/api/agenda/login",
                json={"username": "nope", "password": "wrong"},
                headers={"Origin": ORIGIN},
            ).status_code
            == 401
        )
    assert (
        browser.post(
            "/api/agenda/login",
            json={"username": "nope", "password": "wrong"},
            headers={"Origin": ORIGIN},
        ).status_code
        == 429
    )
    sign_in(browser)
    with db() as session:
        session.query(StaffSession).delete()
        session.commit()
    assert browser.get("/api/agenda/session").status_code == 401


def test_panel_security_headers_and_no_private_pwa_cache(browser):
    page = browser.get("/panel")
    assert page.status_code == 200 and "Content-Security-Policy" in page.headers
    assert page.headers["cache-control"] == "no-store"
    assert "token=" not in browser.get("/agenda-assets/panel.webmanifest").text
    worker = browser.get("/panel-sw.js").text
    assert "caches.open" not in worker and "caches.put" not in worker


def test_new_barber_config_without_code_changes(db, monkeypatch):
    monkeypatch.setenv(
        "BARBERS",
        json.dumps([{"name": "Luis", "phone": "6145555555", "hours": {"6": [[600, 720]]}}]),
    )
    get_settings.cache_clear()
    assert staff.scope("6145555555") == "Luis" and staff.key("luis") == "Luis"
    assert staff.working_slot("Luis", datetime(2026, 11, 1, 10))
    assert not staff.working_slot("Luis", datetime(2026, 11, 1, 12))
    with db() as session:
        ctx = SimpleNamespace(deps=BotDeps(wa_id=CLIENT, db=session))
        assert "Luis" in tools.consultar_disponibilidad(ctx, "2026-11-02", "Nobody")
        assert "no hay espacios" in tools.consultar_disponibilidad(ctx, "2026-11-02", "Luis")


def test_template_payload_and_unknown_transport(db, monkeypatch):
    # Restore the real transport helper without making external requests.
    real = REAL_TEMPLATE_SENDER
    monkeypatch.setenv("REMINDER_TEMPLATE_NAME", "test_approved_reminder")
    get_settings.cache_clear()
    with db() as session:
        row = appointment(session)
        n = reminders.stage_notice(session, row, "reminder", NOW)
        post = Mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.mock"}]}))
        monkeypatch.setattr(httpx, "post", post)
        assert real(n, row) == ("sent", "wamid.mock", None)
        sent = post.call_args.kwargs["json"]
        assert sent["template"]["name"] == "test_approved_reminder"
        assert sent["biz_opaque_callback_data"] == f"waia:{n.id}:{n.event_id}"
        post.side_effect = httpx.ReadTimeout("synthetic timeout")
        assert real(n, row)[0] == "uncertain"


def test_consent_cannot_override_customer_opt_out_or_other_barber(browser, db):
    with db() as session:
        own = appointment(session, 30, consent=False)
        foreign = appointment(session, 30, "Jesús", consent=False)
        session.add(MessagingPreference(wa_id=CLIENT, opted_out=True))
        session.commit()
    headers = sign_in(browser)
    body = {"enabled": True, "source": "Permiso explícito simulado en persona"}
    assert (
        browser.post(
            f"/api/agenda/appointments/{foreign.id}/consent", headers=headers, json=body
        ).status_code
        == 404
    )
    assert (
        browser.post(
            f"/api/agenda/appointments/{own.id}/consent", headers=headers, json=body
        ).status_code
        == 409
    )
    with db() as session:
        assert not session.get(Appointment, own.id).reminder_consent


def test_block_admin_permissions_and_stale_status(browser, db):
    headers = sign_in(browser)
    body = {
        "barber": "Obed",
        "starts_at": "2026-11-01T15:00:00",
        "ends_at": "2026-11-01T16:00:00",
        "reason": "Descanso de prueba",
    }
    assert browser.post("/api/agenda/blocks", headers=headers, json=body).status_code == 403
    with db() as session:
        row = appointment(session, -30, status="arrived")
        session.commit()
    response = browser.post(
        f"/api/agenda/appointments/{row.id}/state",
        headers=headers,
        json={"state": "completed", "expected_status": "confirmed"},
    )
    assert response.status_code == 409
    headers = sign_in(browser, "owner")
    response = browser.post("/api/agenda/blocks", headers=headers, json=body)
    assert response.status_code == 200
    identity = response.json()["id"]
    assert browser.post("/api/agenda/blocks", headers=headers, json=body).status_code == 409
    assert browser.delete(f"/api/agenda/blocks/{identity}", headers=headers).status_code == 200
    with db() as session:
        assert session.get(Appointment, row.id).status == "arrived"


def test_panel_body_limit_also_checks_stream_without_content_length(browser):
    headers = {"Origin": ORIGIN, "Content-Type": "application/json"}
    response = browser.post(
        "/api/agenda/login", headers=headers, content=iter([b" " * 10000, b" " * 10000])
    )
    assert response.status_code == 413
    response = browser.post(
        "/api/agenda/login", headers=headers, json={"username": "unknown", "password": "wrong"}
    )
    assert response.status_code == 401


def test_existing_agenda_displays_new_states_without_mislabeling():
    from app.agenda import _format_row

    for state in ("arrived", "in_service", "no_show"):
        row = Appointment(
            customer_name="Prueba",
            service="corte normal",
            barber="Obed",
            starts_at=NOW,
            status=state,
        )
        assert scheduling.LABELS[state] in _format_row(row)


def test_rejected_booking_releases_calendar_transaction_before_model_response(db):
    with db() as session:
        row = appointment(session, 30)
        session.commit()
        ctx = SimpleNamespace(deps=BotDeps(wa_id=CLIENT, db=session))
        reply = tools.agendar(
            ctx, row.starts_at.strftime("%Y-%m-%d %H:%M"), "corte normal", "Otro cliente", "Obed"
        )
        assert "ocupado" in reply
        assert not session.in_transaction()
    # A different connection can immediately block another slot.
    with db() as session:
        scheduling.create_block(
            session,
            "all",
            "admin",
            "Obed",
            NOW + timedelta(hours=2),
            NOW + timedelta(hours=3),
            "Prueba",
        )
        session.commit()
