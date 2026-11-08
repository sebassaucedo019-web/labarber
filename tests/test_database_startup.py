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
    assert "uq_reserved_barber_slot" in {
        index["name"] for index in inspect(engine).get_indexes("appointments")
    }
    engine.dispose()


def test_conflicting_legacy_bookings_fail_startup_without_deleting_them(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("CALENDAR_UTC_MIGRATION_ENABLED", "true")
    get_settings.cache_clear()
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
                    "INSERT INTO appointments (id,barber,starts_at,status) "
                    "VALUES (:id,'Obed','2090-01-01 12:00','confirmed')"
                ),
                {"id": identity},
            )
    monkeypatch.setattr(postgres, "_engine", engine)
    with pytest.raises(IntegrityError):
        postgres.init_db()
    with engine.connect() as conn:
        assert conn.scalar(text("SELECT COUNT(*) FROM appointments")) == 2
    engine.dispose()


def test_waia_migration_preserves_existing_citas_and_outbox(tmp_path, monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("CALENDAR_UTC_MIGRATION_ENABLED", "true")
    get_settings.cache_clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'waia-legacy.db'}")
    with engine.begin() as conn:
        conn.execute(
            text("""CREATE TABLE appointments (
            id INTEGER PRIMARY KEY, wa_id VARCHAR(32), customer_name VARCHAR(120),
            service VARCHAR(80), barber VARCHAR(80), starts_at DATETIME,
            status VARCHAR(16), created_at DATETIME
        )""")
        )
        conn.execute(
            text("""INSERT INTO appointments
            (id, wa_id, customer_name, service, barber, starts_at, status)
            VALUES (1, '525500000001', 'Cliente de prueba', 'corte normal',
                    'Obed', '2030-01-01 12:00:00', 'confirmed')""")
        )
        conn.execute(
            text("""CREATE TABLE notification_outbox (
            id INTEGER PRIMARY KEY, event_id VARCHAR(32), appointment_id INTEGER,
            recipient VARCHAR(32), message TEXT, status VARCHAR(16), attempts INTEGER,
            next_attempt_at DATETIME, lease_token VARCHAR(64), last_error VARCHAR(300),
            created_at DATETIME, accepted_at DATETIME
        )""")
        )
        conn.execute(
            text("""INSERT INTO notification_outbox
            (id,event_id,appointment_id,recipient,message,status,attempts)
            VALUES (1,'existing-event',1,'525500000001','Confirmación pendiente','pending',2)
        """)
        )
    monkeypatch.setattr(postgres, "_engine", engine)
    postgres.init_db()
    postgres.init_db()
    with engine.connect() as conn:
        appointment = conn.execute(text("SELECT * FROM appointments")).mappings().one()
        assert appointment["customer_name"] == "Cliente de prueba"
        assert appointment["status"] == "confirmed"
        assert not appointment["reminder_consent"]
        assert appointment["completed_at"] is None
        notice = conn.execute(text("SELECT * FROM notification_outbox")).mappings().one()
        assert notice["status"] == "pending" and notice["attempts"] == 2
        assert notice["message"] == "Confirmación pendiente"
        assert notice["kind"] == "appointment"
        assert notice["provider_message_id"] is None
    tables = set(inspect(engine).get_table_names())
    assert {"appointment_events", "schedule_blocks"} <= tables
    assert not {"staff_accounts", "staff_sessions"} & tables
    engine.dispose()
