import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.store import postgres


def test_initialization_adds_booking_index_on_existing_table(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as conn:
        conn.execute(
            text("""CREATE TABLE appointments (
            id INTEGER PRIMARY KEY, wa_id VARCHAR(32), customer_name VARCHAR(120),
            service VARCHAR(80), starts_at DATETIME, status VARCHAR(16), created_at DATETIME
        )""")
        )
    monkeypatch.setattr(postgres, "_engine", engine)
    postgres.init_db()
    postgres.init_db()
    assert "barber" in {column["name"] for column in inspect(engine).get_columns("appointments")}
    assert "uq_confirmed_barber_slot" in {
        index["name"] for index in inspect(engine).get_indexes("appointments")
    }
    engine.dispose()


def test_conflicting_legacy_bookings_fail_startup_without_deleting_them(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'conflicts.db'}")
    with engine.begin() as conn:
        conn.execute(
            text("""CREATE TABLE appointments (
            id INTEGER PRIMARY KEY, wa_id VARCHAR(32), customer_name VARCHAR(120),
            service VARCHAR(80), barber VARCHAR(80), starts_at DATETIME,
            status VARCHAR(16), created_at DATETIME
        )""")
        )
        for identity in (1, 2):
            conn.execute(
                text(
                    "INSERT INTO appointments (id,barber,starts_at,status) VALUES (:id,'Obed','2090-01-01 12:00','confirmed')"
                ),
                {"id": identity},
            )
    monkeypatch.setattr(postgres, "_engine", engine)
    with pytest.raises(IntegrityError):
        postgres.init_db()
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM appointments")) == 2
    engine.dispose()
