from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.agent.deps import BotDeps
from app.agent.tools import (
    _notify_staff_of_appointment,
    agendar,
    cancelar_cita,
    consultar_disponibilidad,
    consultar_mi_cita,
    reagendar_cita,
    ver_agenda,
    ver_siguiente_cita,
)
from app.agenda import create_agenda_link
from app.config import get_settings
from app.store.models import Appointment, Base


def make_deps(wa_id: str = "5216143649949") -> tuple[Session, BotDeps]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    return session, BotDeps(wa_id=wa_id, db=session)


def as_ctx(deps: BotDeps) -> SimpleNamespace:
    return SimpleNamespace(deps=deps)


def test_agendar_guarda_y_evita_traslape():
    session, deps = make_deps()
    when = datetime.now() + timedelta(days=1)
    when = when.replace(hour=17, minute=0, second=0, microsecond=0)

    result = agendar(as_ctx(deps), when.strftime("%Y-%m-%d %H:%M"), "corte clásico", "Sebastián", "Obed")
    duplicate = agendar(as_ctx(deps), when.strftime("%Y-%m-%d %H:%M"), "corte clásico", "Sebastián", "Obed")

    assert "Cita confirmada" in result
    assert "ocupado" in duplicate


def test_cancelar_respeta_tres_horas():
    session, deps = make_deps()
    when = datetime.now() + timedelta(hours=2)
    when = when.replace(second=0, microsecond=0)
    session.add(Appointment(
        wa_id=deps.wa_id,
        customer_name="Sebastián",
        service="corte normal",
        starts_at=when,
    ))
    session.commit()

    result = cancelar_cita(as_ctx(deps), when.strftime("%Y-%m-%d %H:%M"))

    assert "3 horas" in result


def _set_staff_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OWNER_WA_ID", "5216110000000")
    monkeypatch.setenv("BARBER_OBED_WA_ID", "5216111111111")
    monkeypatch.setenv("BARBER_JESUS_WA_ID", "5216112222222")
    monkeypatch.setenv("BARBER_YADIER_WA_ID", "5216113333333")
    get_settings.cache_clear()


def test_cliente_no_ve_agenda(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_staff_ids(monkeypatch)
    session, deps = make_deps("5216999999999")
    assert "únicamente" in ver_agenda(as_ctx(deps))
    get_settings.cache_clear()


def test_cliente_consulta_solo_sus_citas() -> None:
    session, deps = make_deps("5216140000001")
    when = datetime.now() + timedelta(days=1)
    when = when.replace(hour=10, minute=0, second=0, microsecond=0)
    session.add(Appointment(
        wa_id=deps.wa_id,
        customer_name="Ana",
        service="corte normal",
        barber="Obed",
        starts_at=when,
    ))
    session.add(Appointment(
        wa_id="5216140000002",
        customer_name="Luis",
        service="corte clásico",
        barber="Yadier",
        starts_at=when.replace(hour=11),
    ))
    session.commit()

    result = consultar_mi_cita(as_ctx(deps))

    assert "Ana" in result
    assert "Luis" not in result


def test_dueno_ve_todas_y_barbero_solo_las_suyas(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_staff_ids(monkeypatch)

    session, owner_deps = make_deps("5216110000000")
    when = datetime.now() + timedelta(days=1)
    when = when.replace(hour=10, minute=0, second=0, microsecond=0)
    session.add(Appointment(
        wa_id="5216140000001",
        customer_name="Ana",
        service="corte normal",
        barber="Obed",
        starts_at=when,
    ))
    session.add(Appointment(
        wa_id="5216140000002",
        customer_name="Luis",
        service="corte clásico",
        barber="Yadier",
        starts_at=when.replace(hour=11),
    ))
    session.commit()

    owner_list = ver_agenda(as_ctx(owner_deps))
    assert "Ana" in owner_list
    assert "Luis" in owner_list

    barber_deps = BotDeps(wa_id="5216111111111", db=session)
    barber_list = ver_agenda(as_ctx(barber_deps))
    assert "Ana" in barber_list
    assert "Luis" not in barber_list
    assert "Obed" in ver_siguiente_cita(as_ctx(barber_deps))
    get_settings.cache_clear()


def test_agenda_link_only_staff_can_create_it(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_staff_ids(monkeypatch)
    owner_link = create_agenda_link("5216110000000")
    customer_link = create_agenda_link("5216999999999")

    assert owner_link is not None
    assert owner_link.startswith("https://labarber-production-b9de.up.railway.app/agenda?token=")
    assert customer_link is None
    get_settings.cache_clear()


def test_confirmed_appointment_notifies_owner_and_assigned_barber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_staff_ids(monkeypatch)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.agent.tools.send_text",
        lambda recipient, message: sent.append((recipient, message)),
    )
    appointment = Appointment(
        wa_id="5216140000001",
        customer_name="Ana",
        service="corte normal",
        barber="Obed",
        starts_at=datetime.now() + timedelta(days=1),
    )

    _notify_staff_of_appointment(appointment)

    assert {recipient for recipient, _ in sent} == {"5216110000000", "5216111111111"}
    assert all("La cita quedó confirmada" in message for _, message in sent)
    get_settings.cache_clear()


def test_cancel_and_reschedule_notify_staff(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_staff_ids(monkeypatch)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.agent.tools.send_text",
        lambda recipient, message: sent.append((recipient, message)),
    )
    session, deps = make_deps("5216999999999")
    first = datetime.now() + timedelta(days=2)
    first = first.replace(hour=10, minute=0, second=0, microsecond=0)
    second = first.replace(hour=11)
    session.add(Appointment(
        wa_id=deps.wa_id,
        customer_name="Ana",
        service="corte normal",
        barber="Obed",
        starts_at=first,
    ))
    session.commit()

    result = reagendar_cita(
        as_ctx(deps), first.strftime("%Y-%m-%d %H:%M"), second.strftime("%Y-%m-%d %H:%M")
    )
    assert "reagendada" in result
    assert any("reagendada" in message for _, message in sent)

    sent.clear()
    result = cancelar_cita(as_ctx(deps), second.strftime("%Y-%m-%d %H:%M"))
    assert "cancelada" in result
    assert any("cancelada" in message for _, message in sent)
    get_settings.cache_clear()


def test_reschedule_can_change_barber_and_notifies_new_staff(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_staff_ids(monkeypatch)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.agent.tools.send_text",
        lambda recipient, message: sent.append((recipient, message)),
    )
    session, deps = make_deps("5216999999999")
    first = datetime.now() + timedelta(days=2)
    first = first.replace(hour=10, minute=0, second=0, microsecond=0)
    second = first.replace(hour=11)
    session.add(Appointment(
        wa_id=deps.wa_id,
        customer_name="Ana",
        service="corte normal",
        barber="Jesús",
        starts_at=first,
    ))
    session.commit()

    result = reagendar_cita(
        as_ctx(deps), first.strftime("%Y-%m-%d %H:%M"), second.strftime("%Y-%m-%d %H:%M"), "Obed"
    )

    assert "con Obed" in result
    saved = session.scalar(select(Appointment).where(Appointment.wa_id == deps.wa_id))
    assert saved is not None and saved.barber == "Obed"
    recipients = {recipient for recipient, _ in sent}
    assert {"5216110000000", "5216111111111", "5216112222222"} == recipients
    assert any("Cambio de barbero" in message for _, message in sent)
    assert all("Antes:" not in message for _, message in sent if message.startswith("Cambio de barbero en"))
    get_settings.cache_clear()


def test_availability_does_not_offer_past_slots_today(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import tools

    session, deps = make_deps()
    monkeypatch.setattr(tools, "_now", lambda: datetime(2026, 10, 15, 15, 15))

    result = consultar_disponibilidad(as_ctx(deps), "2026-10-15", "Obed")

    assert "09:00" not in result
    assert "15:00" not in result
    assert "15:30" in result


def test_booking_rejects_closing_time_and_invalid_minutes() -> None:
    session, deps = make_deps()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    at_closing = agendar(
        as_ctx(deps), f"{tomorrow} 20:00", "corte normal", "Ana", "Obed"
    )
    invalid_minutes = agendar(
        as_ctx(deps), f"{tomorrow} 10:15", "corte normal", "Ana", "Obed"
    )

    assert "09:00 a 20:00" in at_closing
    assert "09:00 a 20:00" in invalid_minutes
