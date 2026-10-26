from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import agenda
from app.agent import tools
from app.agent.deps import BotDeps
from app.config import get_settings
from app.store.models import Appointment, Base


@pytest.fixture(autouse=True)
def business_rules_after_confirmation(monkeypatch):
    monkeypatch.setattr(tools, "confirm_action", lambda *args: True)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture
def staff(monkeypatch):
    monkeypatch.setenv("OWNER_WA_ID", "6140000000")
    monkeypatch.setenv("BARBER_OBED_WA_ID", "6141111111")
    get_settings.cache_clear()


def appointment(db, name="Ana", barber="Obed", wa_id="5216149999999", when=None):
    row = Appointment(
        wa_id=wa_id,
        customer_name=name,
        service="corte normal",
        barber=barber,
        starts_at=when
        or (tools._now() + timedelta(days=2)).replace(hour=12, minute=0, second=0, microsecond=0),
    )
    db.add(row)
    db.commit()
    return row


def ctx(db, wa_id="5216149999999", message=""):
    return SimpleNamespace(deps=BotDeps(wa_id=wa_id, db=db, user_message=message))


def test_international_suffix_cannot_impersonate_staff(staff, db):
    assert agenda.staff_scope("5216140000000") == "all"
    assert agenda.staff_scope("526140000000") == "all"
    assert agenda.staff_scope("16140000000") is None
    assert tools._staff_access("16141111111") == (False, None)
    assert agenda.create_agenda_link("16140000000") is None


def test_token_expires_at_boundary_and_revokes_with_staff_change(staff, monkeypatch):
    monkeypatch.setattr(agenda.time, "time", lambda: 1000)
    link = agenda.create_agenda_link("6141111111")
    token = parse_qs(urlparse(link).query)["token"][0]
    assert agenda._verify_token(token) == "Obed"
    monkeypatch.setenv("BARBER_OBED_WA_ID", "6142222222")
    get_settings.cache_clear()
    assert agenda._verify_token(token) is None
    monkeypatch.setenv("BARBER_OBED_WA_ID", "6141111111")
    get_settings.cache_clear()
    monkeypatch.setattr(agenda.time, "time", lambda: 1000 + agenda.TOKEN_TTL_SECONDS)
    assert agenda._verify_token(token) is None
    assert agenda._verify_token("ñ.ñ") is None


def test_same_time_reschedule_requires_selection(db):
    first = appointment(db)
    second = appointment(db, "Luis", "Yadier", when=first.starts_at)
    old = first.starts_at.strftime("%Y-%m-%d %H:%M")
    new = (first.starts_at + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    result = tools.reagendar_cita(ctx(db), old, new)
    assert "varias citas" in result
    assert first.starts_at == second.starts_at
    result = tools.reagendar_cita(ctx(db), old, new, cliente="Luis")
    assert "reagendada" in result
    assert first.starts_at != second.starts_at


def test_customer_cannot_use_another_customers_id(db):
    mine = appointment(db)
    other = appointment(db, "Otro", "Yadier", wa_id="5216148888888", when=mine.starts_at)
    result = tools.cancelar_cita(
        ctx(db), mine.starts_at.strftime("%Y-%m-%d %H:%M"), cita_id=other.id
    )
    assert "No encontré" in result
    assert mine.status == other.status == "confirmed"


def test_barber_cannot_cancel_another_barbers_appointment(db, staff):
    row = appointment(db, barber="Yadier")
    result = tools.cancelar_cita(ctx(db, "6141111111"), row.starts_at.strftime("%Y-%m-%d %H:%M"))
    assert "No encontré" in result
    assert row.status == "confirmed"


def test_staff_cancel_notifies_customer_and_has_receipt(db, staff, monkeypatch):
    row = appointment(db, when=tools._now() + timedelta(minutes=20))
    sent = []
    monkeypatch.setattr(
        tools, "_send_notification", lambda to, text, **kwargs: sent.append((to, text))
    )
    caller = ctx(db, "5216141111111")
    # Tools accept minute precision, as all actual bookings do.
    row.starts_at = row.starts_at.replace(second=0, microsecond=0)
    db.commit()
    result = tools.cancelar_cita(caller, row.starts_at.strftime("%Y-%m-%d %H:%M"))
    assert row.status == "cancelled"
    assert caller.deps.completed_actions == [result]
    assert row.wa_id in [to for to, _ in sent]


def test_customer_same_slot_cancellation_filters_name(db):
    first = appointment(db)
    second = appointment(db, "Luis", "Yadier", when=first.starts_at)
    result = tools.cancelar_cita(ctx(db), first.starts_at.strftime("%Y-%m-%d %H:%M"), "Luis")
    assert "cancelada" in result
    assert first.status == "confirmed" and second.status == "cancelled"


def test_customer_can_find_existing_legacy_number_bookings(db):
    appointment(db)
    assert "Ana" in tools.consultar_mi_cita(ctx(db, "526149999999"))


def test_rescheduling_same_slot_is_noop(db, monkeypatch):
    row = appointment(db)
    called = []
    monkeypatch.setattr(tools, "_send_notification", lambda *args, **kwargs: called.append(args))
    when = row.starts_at.strftime("%Y-%m-%d %H:%M")
    assert "ya tiene" in tools.reagendar_cita(ctx(db), when, when)
    assert not called


def test_past_appointment_cannot_be_revived(db):
    row = appointment(db, when=tools._now() - timedelta(days=1))
    result = tools.reagendar_cita(
        ctx(db), row.starts_at.strftime("%Y-%m-%d %H:%M"), "2090-01-01 12:00"
    )
    assert "ya pasó" in result or "No encontré" in result


def test_database_rejects_double_booking_but_allows_reusing_cancelled_slot(db):
    row = appointment(db)
    db.add(
        Appointment(
            wa_id="other",
            customer_name="Other",
            service="corte normal",
            barber=row.barber,
            starts_at=row.starts_at,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    row.status = "cancelled"
    db.commit()
    replacement = appointment(db, "Other", when=row.starts_at)
    assert replacement.status == "confirmed"


def test_agenda_shows_more_than_fifty_and_escapes_names(db, staff, monkeypatch):
    fixed = tools._now().replace(hour=8, minute=0, second=0, microsecond=0)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed

    monkeypatch.setattr(agenda, "datetime", Clock)
    for day in range(3):
        for slot in range(20):
            appointment(
                db,
                name='<script>alert("x")</script>',
                when=fixed + timedelta(days=day, hours=1, minutes=30 * slot),
            )
    monkeypatch.setattr(agenda, "get_session", lambda: db)
    token = parse_qs(urlparse(agenda.create_agenda_link("6140000000")).query)["token"][0]
    response = agenda.agenda_page(token)
    content = response.body.decode()
    assert "60 citas próximas" in content
    assert '<script>alert("x")</script>' not in content
    assert response.headers["referrer-policy"] == "no-referrer"


def test_off_topic_escalation_cannot_be_authorized_by_model_reason(db, monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "notify_human", lambda *args: calls.append(args))
    tools.escalar_humano(ctx(db, message="Qué clima hace"), "El dueño debe atender una queja")
    assert not calls


def test_support_delivery_failure_is_not_reported_as_success(db, monkeypatch):
    monkeypatch.setattr(tools, "notify_human", lambda *args: False)
    result = tools.escalar_humano(
        ctx(db, message="Quiero hablar con una persona"), "Solicitud de atención"
    )
    assert "No pude entregar" in result
