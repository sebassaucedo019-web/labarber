import sqlite3
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.store import postgres
from app.store.calendar_time import to_utc
from app.store.models import Appointment, NotificationOutbox, PendingAction, ScheduleBlock


def legacy_engine(path):
    engine = create_engine(f"sqlite:///{path}")
    with engine.begin() as connection:
        connection.execute(
            text("""CREATE TABLE appointments (
            id INTEGER PRIMARY KEY, wa_id VARCHAR(32), customer_name VARCHAR(120),
            service VARCHAR(80), barber VARCHAR(80), starts_at DATETIME NOT NULL,
            status VARCHAR(16), created_at DATETIME)""")
        )
        connection.execute(
            text("""INSERT INTO appointments VALUES
            (1, '525500000001', 'Ana', 'corte normal', 'Obed',
             '2026-11-07 10:00:00', 'confirmed', '2026-11-01 18:00:00'),
            (2, '525500000002', 'Luis', 'corte normal', 'Obed',
             '2026-11-07 16:00:00', 'confirmed', '2026-11-01 18:00:00')""")
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX uq_reserved_barber_slot ON appointments(starts_at, barber) "
                "WHERE status != 'cancelled'"
            )
        )
    return engine


def test_existing_data_requires_explicit_maintenance_and_rolls_back(tmp_path, monkeypatch):
    engine = legacy_engine(tmp_path / "legacy.db")
    monkeypatch.setattr(postgres, "_engine", engine)
    with pytest.raises(RuntimeError, match="mantenimiento"):
        postgres.init_db()
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT starts_at FROM appointments WHERE id=1")).scalar()
            == "2026-11-07 10:00:00"
        )
        assert connection.execute(
            text("SELECT name FROM sqlite_master WHERE name='uq_reserved_barber_slot'")
        ).first()
    engine.dispose()


def test_migration_is_once_only_and_backup_restores_original_times(tmp_path, monkeypatch):
    original, backup = tmp_path / "legacy.db", tmp_path / "backup.db"
    engine = legacy_engine(original)
    # Exercise a real SQLite backup/restore into a disposable file, never production.
    with sqlite3.connect(original) as source, sqlite3.connect(backup) as target:
        source.backup(target)
    monkeypatch.setattr(postgres, "_engine", engine)
    monkeypatch.setenv("CALENDAR_UTC_MIGRATION_ENABLED", "true")
    get_settings.cache_clear()
    postgres.init_db()
    postgres.init_db()
    with engine.connect() as connection:
        value = connection.execute(text("SELECT starts_at FROM appointments WHERE id=1")).scalar()
        assert datetime.fromisoformat(value) == datetime(2026, 11, 7, 16)
        assert connection.execute(text("SELECT COUNT(*) FROM appointments")).scalar() == 2
    with Session(engine) as db:
        row = db.get(Appointment, 1)
        assert row.starts_at == datetime(2026, 11, 7, 10)
        assert row.duration_minutes == 30
        assert (
            db.scalar(
                select(Appointment).where(Appointment.starts_at == datetime(2026, 11, 7, 10))
            ).id
            == 1
        )
    restored = tmp_path / "restored.db"
    with sqlite3.connect(backup) as source, sqlite3.connect(restored) as target:
        source.backup(target)
        assert target.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert (
            target.execute("SELECT starts_at FROM appointments WHERE id=1").fetchone()[0]
            == "2026-11-07 10:00:00"
        )
    engine.dispose()


def test_new_database_uses_utc_for_all_calendar_fields(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    monkeypatch.setattr(postgres, "_engine", engine)
    postgres.init_db()
    local = datetime(2026, 11, 7, 10)
    with Session(engine) as db:
        row = Appointment(
            wa_id="525500000001",
            customer_name="Ana",
            service="corte normal",
            barber="Obed",
            starts_at=local,
        )
        db.add(row)
        db.flush()
        db.add_all(
            [
                PendingAction(
                    wa_id=row.wa_id, action="cancel", payload="{}", turn_id="a", expires_at=local
                ),
                ScheduleBlock(
                    barber="Jesús",
                    starts_at=local,
                    ends_at=local.replace(hour=11),
                    reason="descanso",
                    actor="owner",
                ),
                NotificationOutbox(
                    appointment_id=row.id,
                    recipient=row.wa_id,
                    message="x",
                    event_id="a",
                    available_at=local,
                    scheduled_start=local,
                ),
            ]
        )
        db.commit()
    for table, field in (
        ("appointments", "starts_at"),
        ("schedule_blocks", "starts_at"),
        ("pending_actions", "expires_at"),
        ("notification_outbox", "scheduled_start"),
    ):
        with engine.connect() as connection:
            raw = connection.execute(text(f"SELECT {field} FROM {table}")).scalar()
            assert datetime.fromisoformat(raw).hour == 16
    with engine.connect() as connection:
        # Outbox availability was UTC already and must not be converted again.
        raw = connection.execute(text("SELECT available_at FROM notification_outbox")).scalar()
        assert datetime.fromisoformat(raw).hour == 10
    postgres.init_db()
    with Session(engine) as db:
        assert db.scalar(select(Appointment)).starts_at == local
    engine.dispose()


def test_explicit_offset_and_historical_ambiguous_time():
    assert to_utc(datetime(2026, 11, 7, 16, tzinfo=UTC)) == datetime(2026, 11, 7, 16)
    with pytest.raises(ValueError, match="ambigua"):
        to_utc(datetime(2021, 10, 31, 1, 30))
