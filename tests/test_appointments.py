from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.agent.deps import BotDeps
from app.agent.tools import agendar, cancelar_cita
from app.store.models import Appointment, Base


def make_deps() -> tuple[Session, BotDeps]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    return session, BotDeps(wa_id="5216143649949", db=session)


def test_agendar_guarda_y_evita_traslape():
    session, deps = make_deps()
    when = datetime.now() + timedelta(days=1)
    when = when.replace(hour=17, minute=0, second=0, microsecond=0)

    result = agendar(deps, when.strftime("%Y-%m-%d %H:%M"), "corte clásico", "Sebastián", "Obed")
    duplicate = agendar(deps, when.strftime("%Y-%m-%d %H:%M"), "corte clásico", "Sebastián", "Obed")

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

    result = cancelar_cita(deps, when.strftime("%Y-%m-%d %H:%M"))

    assert "3 horas" in result
