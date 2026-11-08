"""Transactional, one-time conversion of legacy Chihuahua calendar timestamps."""

from datetime import datetime

from sqlalchemy import DateTime, bindparam, text

from app.config import get_settings
from app.store.calendar_time import to_utc

CALENDAR_MIGRATION = "calendar_utc_v1"
CALENDAR_FIELDS = {
    "appointments": (
        "id",
        ("starts_at", "arrived_at", "started_at", "completed_at", "schedule_updated_at"),
    ),
    "schedule_blocks": ("id", ("starts_at", "ends_at")),
    "notification_outbox": ("id", ("scheduled_start",)),
    "pending_actions": ("wa_id", ("expires_at",)),
}


def migrate_calendar_utc(connection, preexisting_tables: set[str]):
    if connection.execute(
        text("SELECT name FROM schema_migrations WHERE name=:name"), {"name": CALENDAR_MIGRATION}
    ).first():
        return
    has_legacy_data = any(
        connection.execute(text(f"SELECT 1 FROM {table} LIMIT 1")).first()
        for table in CALENDAR_FIELDS
        if table in preexisting_tables
    )
    if has_legacy_data and not get_settings().calendar_utc_migration_enabled:
        raise RuntimeError(
            "La conversión de fechas a UTC requiere mantenimiento: respalda la base, "
            "detén las versiones anteriores de web/worker y habilita "
            "CALENDAR_UTC_MIGRATION_ENABLED para migrar."
        )
    if "appointments" in preexisting_tables:
        # Offsetting one row at a time can temporarily overlap another legacy slot.
        # init_db recreates the uniqueness guard before committing this transaction.
        connection.execute(text("DROP INDEX IF EXISTS uq_reserved_barber_slot"))
    for table, (identity, fields) in CALENDAR_FIELDS.items():
        if table not in preexisting_tables:
            continue
        rows = (
            connection.execute(text(f"SELECT {identity}, {', '.join(fields)} FROM {table}"))
            .mappings()
            .all()
        )
        statement = text(
            f"UPDATE {table} SET "
            + ", ".join(f"{field}=:{field}" for field in fields)
            + f" WHERE {identity}=:identity"
        ).bindparams(*(bindparam(field, type_=DateTime()) for field in fields))
        for row in rows:
            changes = {"identity": row[identity]}
            for field in fields:
                value = row[field]
                if isinstance(value, str):
                    value = datetime.fromisoformat(value)
                changes[field] = to_utc(value) if value is not None else None
            connection.execute(statement, changes)
    connection.execute(
        text("INSERT INTO schema_migrations (name) VALUES (:name)"), {"name": CALENDAR_MIGRATION}
    )
