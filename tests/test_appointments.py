from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.deps import BotDeps
from app.agent.tools import agendar, cancelar_cita, ver_agenda, ver_siguiente_cita
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
