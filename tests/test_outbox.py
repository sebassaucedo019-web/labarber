from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timedelta
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, inspect, select
from sqlalchemy.orm import sessionmaker

from app import notifications as outbox
from app.agent import tools
from app.agent.deps import BotDeps
from app.config import get_settings
from app.store import postgres
from app.store.models import Appointment, Base, NotificationOutbox

OWNER = "526141111111"
OBED = "526142222222"
JESUS = "526143333333"
CLIENT = "526144444444"


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'outbox.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(outbox, "get_session", factory)
    monkeypatch.setattr(outbox, "send_text", Mock(return_value=True))
    monkeypatch.setattr(tools, "confirm_action", lambda *args: True)
    for key, value in {
        "OWNER_WA_ID": OWNER,
        "BARBER_OBED_WA_ID": OBED,
        "BARBER_JESUS_WA_ID": JESUS,
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield factory
    engine.dispose()
    get_settings.cache_clear()


@pytest.fixture
def clock(monkeypatch):
    value = [datetime(2026, 10, 26, 12)]
    monkeypatch.setattr(outbox, "_now", lambda: value[0])
    return value


def appointment(session, barber="Obed"):
    row = Appointment(
        wa_id=CLIENT,
        customer_name="Ana",
        service="corte normal",
        barber=barber,
        starts_at=datetime(2090, 1, 2, 12),
    )
    session.add(row)
    session.commit()
    return row


def stage(session, row, recipient=OBED, message="Confirmacion", event_id=None):
    outbox.notify(
        recipient, message, session=session, appointment_id=row.id, event_id=event_id or uuid4().hex
    )


def act(session, operation):
    ctx = SimpleNamespace(deps=BotDeps(wa_id=CLIENT, db=session, user_message="Si confirmo"))
    if operation == "book":
        return tools.agendar(ctx, "2090-01-02 12:00", "corte normal", "Ana", "Obed")
    if operation == "cancel":
        return tools.cancelar_cita(ctx, "2090-01-02 12:00")
    return tools.reagendar_cita(ctx, "2090-01-02 12:00", "2090-01-02 13:00", "Jesús")


@pytest.mark.parametrize("operation", ["book", "cancel", "reschedule"])
def test_changes_and_notifications_commit_together_without_sending(database, operation):
    with database() as session:
        if operation != "book":
            appointment(session)
        act(session, operation)
    with database() as session:
        row = session.scalar(select(Appointment))
        notices = session.scalars(select(NotificationOutbox)).all()
        assert row is not None
        assert {n.recipient for n in notices} == (
            {OWNER, OBED, JESUS} if operation == "reschedule" else {OWNER, OBED}
        )
        assert len({n.event_id for n in notices}) == 1
        assert all(n.appointment_id == row.id and n.status == "pending" for n in notices)
        assert row.status == ("cancelled" if operation == "cancel" else "confirmed")
        assert row.starts_at.hour == (13 if operation == "reschedule" else 12)
    outbox.send_text.assert_not_called()


@pytest.mark.parametrize("operation", ["book", "cancel", "reschedule"])
def test_staging_failure_rolls_back_change_and_all_notices(database, monkeypatch, operation):
    original = outbox.notify
    calls = []

    def fail_second(*args, **kwargs):
        original(*args, **kwargs)
        calls.append(args)
        if len(calls) == 2:
            raise RuntimeError("outbox insert unavailable")

    with database() as session:
        if operation != "book":
            appointment(session)
        monkeypatch.setattr(outbox, "notify", fail_second)
        with pytest.raises(RuntimeError, match="insert unavailable"):
            act(session, operation)
    with database() as session:
        assert session.scalar(select(func.count()).select_from(NotificationOutbox)) == 0
        row = session.scalar(select(Appointment))
        if operation == "book":
            assert row is None
        else:
            assert row.status == "confirmed" and row.starts_at.hour == 12 and row.barber == "Obed"
    outbox.send_text.assert_not_called()


def test_commit_failure_leaves_neither_booking_nor_notice(database, monkeypatch):
    with database() as session:
        monkeypatch.setattr(session, "commit", Mock(side_effect=RuntimeError("commit failed")))
        with pytest.raises(RuntimeError, match="commit failed"):
            act(session, "book")
    with database() as session:
        assert session.scalar(select(Appointment)) is None
        assert session.scalar(select(NotificationOutbox)) is None


def test_restart_after_commit_recovers_notices_without_redis(database):
    with database() as session:
        act(session, "book")
    # A new DB session recovers the durable rows even if no Redis job was ever created.
    assert outbox.dispatch_pending() == 2
    assert outbox.dispatch_pending() == 0
    assert outbox.send_text.call_count == 2
    with database() as session:
        assert all(
            n.status == "sent" and n.accepted_at
            for n in session.scalars(select(NotificationOutbox))
        )


def test_uncommitted_notice_cannot_be_claimed(database):
    with database() as session:
        row = appointment(session)
        stage(session, row)
        session.flush()
        # A read-only independent connection sees only committed events.
        with database() as other:
            assert other.scalar(select(NotificationOutbox)) is None
        session.rollback()
    assert outbox.dispatch_pending() == 0


def test_failed_send_is_retried_only_when_due(database, clock):
    with database() as session:
        stage(session, appointment(session))
        session.commit()
    outbox.send_text.side_effect = [False, True]
    assert outbox.dispatch_pending() == 1
    assert outbox.dispatch_pending() == 0
    clock[0] += timedelta(seconds=16)
    assert outbox.dispatch_pending() == 1
    with database() as session:
        row = session.scalar(select(NotificationOutbox))
        assert row.attempts == 2 and row.status == "sent" and row.last_error is None


def test_dead_worker_lease_expires_and_old_worker_cannot_ack(database, clock):
    with database() as session:
        stage(session, appointment(session))
        session.commit()
    old = outbox.claim_notification()
    assert old is not None and outbox.claim_notification() is None
    clock[0] += timedelta(seconds=outbox.LEASE_SECONDS + 1)
    new = outbox.claim_notification()
    assert new is not None and new.token != old.token
    assert not outbox.finish_delivery(old, True)
    with database() as session:
        assert session.get(NotificationOutbox, new.id).lease_token == new.token
    assert outbox.finish_delivery(new, True)
    assert outbox.claim_notification() is None


def test_two_workers_do_not_claim_same_row(database):
    with database() as session:
        stage(session, appointment(session))
        session.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: outbox.claim_notification(), range(2)))
    assert sum(result is not None for result in results) == 1


def test_change_order_survives_retry_without_blocking_other_recipients(database, clock):
    with database() as session:
        row = appointment(session)
        stage(session, row, message="Original")
        stage(session, row, message="Cambio")
        stage(session, row, recipient=OWNER, message="Aviso al dueno")
        session.commit()
    outbox.send_text.side_effect = [False, True, True, True]
    assert outbox.dispatch_pending() == 2
    assert [c.args[1] for c in outbox.send_text.call_args_list] == ["Original", "Aviso al dueno"]
    clock[0] += timedelta(seconds=16)
    assert outbox.dispatch_pending() == 2
    assert [c.args[1] for c in outbox.send_text.call_args_list][-2:] == ["Original", "Cambio"]


def test_exhausted_delivery_is_retained_and_not_retried_forever(database, clock):
    with database() as session:
        stage(session, appointment(session))
        session.commit()
    outbox.send_text.return_value = False
    for _ in range(outbox.MAX_ATTEMPTS):
        assert outbox.dispatch_pending() == 1
        clock[0] += timedelta(hours=2)
    assert outbox.dispatch_pending() == 0
    with database() as session:
        row = session.scalar(select(NotificationOutbox))
        assert row.status == "failed" and row.attempts == outbox.MAX_ATTEMPTS
        assert row.message == "Confirmacion" and row.last_error == "delivery_rejected"


def test_crash_on_final_attempt_becomes_failed_after_lease_expiry(database, clock):
    with database() as session:
        stage(session, appointment(session))
        session.commit()
        row = session.scalar(select(NotificationOutbox))
        row.attempts = outbox.MAX_ATTEMPTS - 1
        session.commit()
    assert outbox.claim_notification().attempts == outbox.MAX_ATTEMPTS
    clock[0] += timedelta(seconds=outbox.LEASE_SECONDS + 1)
    assert outbox.claim_notification() is None
    with database() as session:
        assert session.scalar(select(NotificationOutbox)).status == "failed"


def test_acceptance_then_db_failure_keeps_recoverable_lease(database, clock, monkeypatch):
    with database() as session:
        stage(session, appointment(session))
        session.commit()
    finish = outbox.finish_delivery
    monkeypatch.setattr(outbox, "finish_delivery", Mock(side_effect=RuntimeError("db unavailable")))
    with pytest.raises(RuntimeError):
        outbox.dispatch_pending()
    outbox.send_text.assert_called_once()
    with database() as session:
        assert session.scalar(select(NotificationOutbox)).status == "sending"
    monkeypatch.setattr(outbox, "finish_delivery", finish)
    clock[0] += timedelta(seconds=outbox.LEASE_SECONDS + 1)
    assert outbox.dispatch_pending() == 1
    # This unavoidable network/commit ambiguity can duplicate a message, not lose it.
    assert outbox.send_text.call_count == 2


def test_same_event_deduplicates_mexican_number_aliases(database):
    with database() as session:
        row = appointment(session)
        stage(session, row, recipient="6142222222", event_id="same")
        stage(session, row, recipient="5216142222222", event_id="same")
        session.commit()
        assert session.scalar(select(func.count()).select_from(NotificationOutbox)) == 1


def test_owner_also_assigned_barber_receives_one_notice(database, monkeypatch):
    monkeypatch.setenv("BARBER_OBED_WA_ID", "5216141111111")
    get_settings.cache_clear()
    with database() as session:
        act(session, "book")
        notices = session.scalars(select(NotificationOutbox)).all()
        assert len(notices) == 1 and notices[0].recipient == OWNER


def test_barber_cancellation_persists_customer_notice_in_same_event(database):
    with database() as session:
        row = appointment(session)
        ctx = SimpleNamespace(deps=BotDeps(wa_id=OBED, db=session, user_message="Si"))
        assert "cancelada" in tools.cancelar_cita(ctx, "2090-01-02 12:00", cita_id=row.id)
        notices = session.scalars(select(NotificationOutbox)).all()
        assert {n.recipient for n in notices} == {OWNER, OBED, CLIENT}
        assert len({n.event_id for n in notices}) == 1


def test_legacy_owner_booking_cancellation_does_not_duplicate_owner_notice(database):
    with database() as session:
        row = appointment(session)
        row.wa_id = OWNER
        session.commit()
        ctx = SimpleNamespace(deps=BotDeps(wa_id=OBED, db=session, user_message="Si"))
        assert "cancelada" in tools.cancelar_cita(ctx, "2090-01-02 12:00", cita_id=row.id)
        assert session.scalar(select(func.count()).select_from(NotificationOutbox)) == 2


def test_database_initialization_adds_outbox_without_changing_existing_appointment(
    database, monkeypatch
):
    with database() as session:
        row = appointment(session)
        engine = session.get_bind()
        NotificationOutbox.__table__.drop(engine)
        monkeypatch.setattr(postgres, "_engine", engine)
        postgres.init_db()
        postgres.init_db()
        assert "notification_outbox" in inspect(engine).get_table_names()
        session.expire_all()
        assert session.get(Appointment, row.id).customer_name == "Ana"


def test_loop_retries_database_failure_and_stops_cleanly(monkeypatch):
    stop = Mock()
    stop.is_set.side_effect = [False, False, True]
    dispatch = Mock(side_effect=[RuntimeError("db unavailable"), 0])
    monkeypatch.setattr(outbox, "dispatch_pending", dispatch)
    outbox._dispatch_loop(stop)
    assert dispatch.call_count == 2 and stop.wait.call_count == 2


def test_dispatcher_lifecycle_starts_and_joins_thread(monkeypatch):
    entered, exited = Event(), Event()

    def run(stop):
        entered.set()
        assert stop.wait(5)
        exited.set()

    monkeypatch.setattr(outbox, "_dispatch_loop", run)
    with outbox.outbox_dispatcher():
        assert entered.wait(5)
        assert not exited.is_set()
    assert exited.is_set()


def test_stop_before_claim_does_not_consume_notice(database):
    stop = Event()
    stop.set()
    with database() as session:
        stage(session, appointment(session))
        session.commit()
    assert outbox.dispatch_pending(stop) == 0
    outbox.send_text.assert_not_called()


def test_send_exception_keeps_error_type_without_sensitive_message(database, clock):
    with database() as session:
        stage(session, appointment(session))
        session.commit()
    outbox.send_text.side_effect = RuntimeError("private message or credential")
    assert outbox.dispatch_pending() == 1
    with database() as session:
        row = session.scalar(select(NotificationOutbox))
        assert row.status == "pending" and row.last_error == "RuntimeError"


def test_repeating_booked_slot_does_not_duplicate_notices(database):
    with database() as session:
        act(session, "book")
        assert "ya estaba confirmada" in act(session, "book")
        assert session.scalar(select(func.count()).select_from(NotificationOutbox)) == 2


def test_worker_starts_outbox_after_schema_and_stops_it_on_failure(monkeypatch):
    from app.queue import worker

    events = []

    @contextmanager
    def dispatcher():
        events.append("outbox-start")
        try:
            yield
        finally:
            events.append("outbox-stop")

    def work(**kwargs):
        events.append("work")
        raise RuntimeError("worker stopped")

    monkeypatch.setattr(worker, "init_db", lambda: events.append("init"))
    monkeypatch.setattr(worker, "get_queue", lambda: Mock())
    monkeypatch.setattr(worker, "outbox_dispatcher", dispatcher)
    monkeypatch.setattr(worker, "SimpleWorker", lambda *args, **kwargs: SimpleNamespace(work=work))
    monkeypatch.setattr(worker, "close_async_runner", lambda: events.append("close"))
    with pytest.raises(RuntimeError, match="worker stopped"):
        worker.main()
    assert events == ["init", "outbox-start", "work", "outbox-stop", "close"]
