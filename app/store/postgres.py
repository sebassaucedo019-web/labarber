from __future__ import annotations

import logging

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.observability import hash_wa_id
from app.store.models import Appointment, Base, Conversation, MessageLog

logger = logging.getLogger(__name__)

_database_url = get_settings().database_url
_engine_options = {"pool_pre_ping": True}
if _database_url.startswith("sqlite"):
    _engine_options["connect_args"] = {"check_same_thread": False}

_engine = create_engine(_database_url, **_engine_options)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(_engine)
    if "appointments" in inspect(_engine).get_table_names():
        columns = {column["name"] for column in inspect(_engine).get_columns("appointments")}
        if "barber" not in columns:
            with _engine.begin() as connection:
                connection.execute(text("ALTER TABLE appointments ADD COLUMN barber VARCHAR(80)"))
    # create_all does not add indexes to tables that already existed before the
    # index was introduced. Ensure the booking race-condition guard is present
    # on existing Railway databases too.
    try:
        next(index for index in Appointment.__table__.indexes if index.name == "uq_confirmed_barber_slot").create(
            bind=_engine,
            checkfirst=True,
        )
    except SQLAlchemyError:
        logger.exception("no se pudo asegurar el indice anti doble reserva")


def get_session() -> Session:
    return SessionLocal()


def load_history(session: Session, wa_id: str) -> bytes:
    row = session.get(Conversation, wa_id)
    return row.history_json.encode() if row and row.history_json else b""


def save_history(session: Session, wa_id: str, history_json: bytes) -> None:
    row = session.get(Conversation, wa_id)
    if row is None:
        row = Conversation(wa_id=wa_id, history_json="")
        session.add(row)
    row.history_json = history_json.decode()
    session.commit()


def log_message(session: Session, wa_id: str, direction: str, content: str) -> None:
    session.add(MessageLog(wa_id_hash=hash_wa_id(wa_id), direction=direction, content=content))
    session.commit()
