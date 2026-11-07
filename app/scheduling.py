"""Reservation rules, staff schedules and persistent appointment state."""

from datetime import datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.staff import working_slot
from app.store.models import Appointment, AppointmentEvent, NotificationOutbox, ScheduleBlock

ACTIVE = ("confirmed", "arrived", "in_service")
LABELS = {
    "confirmed": "Confirmada",
    "arrived": "Cliente llegó",
    "in_service": "En atención",
    "completed": "Atendido",
    "cancelled": "Cancelada",
    "no_show": "No asistió",
}
BUSINESS_TZ = ZoneInfo("America/Chihuahua")


def local_now() -> datetime:
    return datetime.now(BUSINESS_TZ).replace(tzinfo=None)


def calendar_lock(session: Session) -> None:
    # Booking and blocks must share a lock; a row lock cannot lock a missing slot.
    if session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(7419303)"))
    elif session.bind.dialect.name == "sqlite":
        session.execute(update(Appointment).where(Appointment.id == -1).values(status="confirmed"))


def close_calendar_transaction(operation):
    """Tool commits are explicit; release read/lock transactions on every early return."""

    @wraps(operation)
    def wrapped(ctx, *args, **kwargs):
        try:
            return operation(ctx, *args, **kwargs)
        finally:
            # A rejected proposal must not hold the shared calendar lock while
            # the model generates its answer or calls another tool.
            ctx.deps.db.rollback()

    return wrapped


def blocked(session: Session, barber: str, at: datetime) -> bool:
    return (
        session.scalar(
            select(ScheduleBlock.id)
            .where(
                ScheduleBlock.barber == barber,
                ScheduleBlock.active.is_(True),
                ScheduleBlock.starts_at < at + timedelta(minutes=30),
                ScheduleBlock.ends_at > at,
            )
            .limit(1)
        )
        is not None
    )


def available(session: Session, barber: str, at: datetime, exclude: int | None = None) -> bool:
    if not working_slot(barber, at) or blocked(session, barber, at):
        return False
    return (
        session.scalar(
            select(Appointment.id)
            .where(
                Appointment.barber == barber,
                Appointment.status != "cancelled",
                Appointment.starts_at == at,
                Appointment.id != (exclude or -1),
            )
            .limit(1)
        )
        is None
    )


def available_times(session, barber, day, now):
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    occupied = set(
        session.scalars(
            select(Appointment.starts_at).where(
                Appointment.barber == barber,
                Appointment.status != "cancelled",
                Appointment.starts_at >= start,
                Appointment.starts_at < end,
            )
        ).all()
    )
    blocks = session.scalars(
        select(ScheduleBlock).where(
            ScheduleBlock.barber == barber,
            ScheduleBlock.active.is_(True),
            ScheduleBlock.starts_at < end,
            ScheduleBlock.ends_at > start,
        )
    ).all()
    return [
        at
        for half in range(48)
        for at in (start + timedelta(minutes=half * 30),)
        if at > now
        and at not in occupied
        and working_slot(barber, at)
        and not any(b.starts_at < at + timedelta(minutes=30) and b.ends_at > at for b in blocks)
    ]


def audit(session, appointment_id, actor, action, detail=""):
    session.add(
        AppointmentEvent(appointment_id=appointment_id, actor=actor, action=action, detail=detail)
    )


def invalidate_notices(session, appointment_id):
    session.execute(
        update(NotificationOutbox)
        .where(
            NotificationOutbox.appointment_id == appointment_id,
            NotificationOutbox.kind != "appointment",
            NotificationOutbox.status.in_(("pending", "sending")),
        )
        .values(status="cancelled", lease_token=None, last_error="appointment_changed")
    )


def transition(
    session, appointment_id: int, scope: str, actor: str, target: str, now: datetime | None = None
) -> Appointment:
    now = now or local_now()
    # Acquire before reading to serialize SQLite as well as PostgreSQL operations.
    calendar_lock(session)
    row = session.scalar(
        select(Appointment).where(Appointment.id == appointment_id).with_for_update()
    )
    if row is None or (scope != "all" and row.barber != scope):
        raise PermissionError("Cita no disponible")
    if row.status == target:
        return row
    allowed = {
        "confirmed": {"arrived", "in_service", "completed", "no_show"},
        "arrived": {"confirmed", "in_service", "completed"},
        "in_service": {"completed"},
    }
    if target not in allowed.get(row.status, set()):
        raise ValueError("Ese cambio de estado no es válido")
    if target == "arrived" and (
        now.date() != row.starts_at.date() or now < row.starts_at - timedelta(hours=2)
    ):
        raise ValueError("La llegada se registra el día de la cita, hasta dos horas antes")
    if target in {"in_service", "completed", "no_show"} and now < row.starts_at:
        raise ValueError("Todavía no inicia el horario reservado")
    if target == "no_show" and now < row.starts_at + timedelta(minutes=15):
        raise ValueError("Espera al menos 15 minutos para registrar la inasistencia")
    previous = row.status
    row.status = target
    if target == "arrived":
        row.arrived_at = now
    elif target == "confirmed":
        row.arrived_at = None
    elif target == "in_service":
        row.started_at = now
    elif target == "completed":
        row.completed_at = now
    audit(session, row.id, actor, target, f"{previous} -> {target}")
    invalidate_notices(session, row.id)
    session.flush()
    if target == "completed":
        from app.reminders import stage_notice

        # Include arrived/in_service: do not skip a present next customer to notify another.
        following = session.scalar(
            select(Appointment)
            .where(
                Appointment.barber == row.barber,
                Appointment.status.in_(ACTIVE),
                Appointment.starts_at > row.starts_at,
            )
            .order_by(Appointment.starts_at, Appointment.id)
            .limit(1)
            .with_for_update()
        )
        if following is not None and timedelta(0) <= following.starts_at - now <= timedelta(
            minutes=30
        ):
            stage_notice(session, following, "next_turn", now)
    return row


def create_block(session, scope, actor, barber, start, end, reason):
    if scope != "all":
        raise PermissionError("Solo el administrador puede bloquear horarios")
    if (
        start >= end
        or end - start > timedelta(days=1)
        or start.date() != (end - timedelta(seconds=1)).date()
    ):
        raise ValueError("Elige un intervalo dentro del mismo día")
    if any(d.minute % 30 or d.second or d.microsecond for d in (start, end)):
        raise ValueError("Los bloques usan intervalos de 30 minutos")
    if start < local_now():
        raise ValueError("No se bloquean horarios pasados")
    calendar_lock(session)
    conflict = session.scalar(
        select(Appointment.id)
        .where(
            Appointment.barber == barber,
            Appointment.status != "cancelled",
            Appointment.starts_at >= start - timedelta(minutes=29),
            Appointment.starts_at < end,
        )
        .limit(1)
    )
    overlap = session.scalar(
        select(ScheduleBlock.id)
        .where(
            ScheduleBlock.barber == barber,
            ScheduleBlock.active.is_(True),
            ScheduleBlock.starts_at < end,
            ScheduleBlock.ends_at > start,
        )
        .limit(1)
    )
    if conflict or overlap:
        raise ValueError("El intervalo ya tiene citas o bloqueos; no se modificó ninguna cita")
    row = ScheduleBlock(barber=barber, starts_at=start, ends_at=end, reason=reason, actor=actor)
    session.add(row)
    session.flush()
    audit(
        session, None, actor, "block", f"{row.id}: {barber} {start.isoformat()} / {end.isoformat()}"
    )
    return row
