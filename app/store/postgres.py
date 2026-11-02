from __future__ import annotations

import logging

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.identity import phone_aliases
from app.observability import hash_wa_id
from app.store.models import Appointment, Base, Conversation, MessageLog

logger = logging.getLogger(__name__)

_database_url = get_settings().database_url
_engine_options = {"pool_pre_ping": True}
if _database_url.startswith("sqlite"):
    _engine_options["connect_args"] = {"check_same_thread": False}
else:
    _engine_options["connect_args"] = {
        "connect_timeout": 5,
        "options": "-c statement_timeout=10000",
    }
    _engine_options["pool_timeout"] = 5

_engine = create_engine(_database_url, **_engine_options)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)


def init_db() -> None:
    with _engine.begin() as connection:
        # Web and worker can start simultaneously on Railway.
        if connection.dialect.name == "postgresql":
            connection.execute(text("SELECT pg_advisory_xact_lock(7419302)"))
        Base.metadata.create_all(connection)
        columns = {column["name"] for column in inspect(connection).get_columns("appointments")}
        if "barber" not in columns:
            connection.execute(text("ALTER TABLE appointments ADD COLUMN barber VARCHAR(80)"))
        additions = {
            "appointments": {
                "arrived_at": "TIMESTAMP",
                "started_at": "TIMESTAMP",
                "completed_at": "TIMESTAMP",
                "schedule_updated_at": "TIMESTAMP",
                "reminder_consent": "BOOLEAN NOT NULL DEFAULT false",
                "consent_source": "VARCHAR(300)",
            },
            "notification_outbox": {
                "kind": "VARCHAR(24) NOT NULL DEFAULT 'appointment'",
                "scheduled_start": "TIMESTAMP",
                "scheduled_barber": "VARCHAR(80)",
                "provider_message_id": "VARCHAR(256)",
                "delivered_at": "TIMESTAMP",
                "read_at": "TIMESTAMP",
            },
        }
        for table, fields in additions.items():
            existing = {col["name"] for col in inspect(connection).get_columns(table)}
            for name, definition in fields.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
        # Existing databases also need the uniqueness guard. Fail startup if
        # conflicting data prevents it; never silently book without protection.
        next(
            index
            for index in Appointment.__table__.indexes
            if index.name == "uq_reserved_barber_slot"
        ).create(
            bind=connection,
            checkfirst=True,
        )


def get_session() -> Session:
    return SessionLocal()


def load_history(session: Session, wa_id: str) -> bytes:
    row = session.scalar(
        select(Conversation)
        .where(Conversation.wa_id.in_(phone_aliases(wa_id)))
        .order_by(Conversation.updated_at.desc())
    )
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
