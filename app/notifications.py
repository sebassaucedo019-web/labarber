"""Durable appointment notifications, independent of Redis availability."""

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from uuid import uuid4

from sqlalchemy import exists, select, update
from sqlalchemy.orm import Session, aliased

from app.identity import normalize_phone
from app.observability import hash_wa_id
from app.sender import send_text
from app.store.models import NotificationOutbox
from app.store.postgres import get_session

logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 8
LEASE_SECONDS = 120
POLL_SECONDS = 5
RETRY_SECONDS = (15, 60, 300, 900, 3600)
ACTIVE_STATUSES = ("pending", "sending")


def _now() -> datetime:
    # All outbox timestamps are UTC, without a timezone for SQLite compatibility.
    return datetime.now(UTC).replace(tzinfo=None)


def notify(
    recipient: str,
    message: str,
    *,
    session: Session,
    appointment_id: int,
    event_id: str,
) -> None:
    """Stage only. The caller must commit this and the appointment atomically."""
    recipient = normalize_phone(recipient)
    if recipient is None or not message.strip():
        raise ValueError("Invalid notification recipient or empty message")
    if any(
        isinstance(row, NotificationOutbox)
        and row.event_id == event_id
        and row.recipient == recipient
        for row in session.new
    ):
        return
    session.add(
        NotificationOutbox(
            appointment_id=appointment_id,
            event_id=event_id,
            recipient=recipient,
            message=message,
            available_at=_now(),
        )
    )


@dataclass(frozen=True)
class Delivery:
    id: int
    recipient: str
    message: str
    attempts: int
    token: str


def _ready(now: datetime):
    older = aliased(NotificationOutbox)
    return (
        NotificationOutbox.status.in_(ACTIVE_STATUSES),
        NotificationOutbox.available_at <= now,
        ~exists().where(
            older.appointment_id == NotificationOutbox.appointment_id,
            older.recipient == NotificationOutbox.recipient,
            older.id < NotificationOutbox.id,
            older.status.in_(ACTIVE_STATUSES),
        ),
    )


def claim_notification() -> Delivery | None:
    now = _now()
    with get_session() as session:
        exhausted = (
            session.execute(
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.status.in_(ACTIVE_STATUSES),
                    NotificationOutbox.available_at <= now,
                    NotificationOutbox.attempts >= MAX_ATTEMPTS,
                )
                .values(status="failed", lease_token=None, last_error="attempts_exhausted")
                .returning(NotificationOutbox.id)
            )
            .scalars()
            .all()
        )
        session.commit()
        for notification_id in exhausted:
            logger.error("outbox agotado id=%s", notification_id)
        candidates = session.scalars(
            select(NotificationOutbox.id)
            .where(*_ready(now))
            .order_by(NotificationOutbox.id)
            .limit(20)
        ).all()
        for notification_id in candidates:
            token = uuid4().hex
            # Conditional UPDATE is the claim: two dispatchers cannot own the same lease.
            row = session.execute(
                update(NotificationOutbox)
                .where(
                    NotificationOutbox.id == notification_id,
                    *_ready(now),
                    NotificationOutbox.attempts < MAX_ATTEMPTS,
                )
                .values(
                    status="sending",
                    lease_token=token,
                    available_at=now + timedelta(seconds=LEASE_SECONDS),
                    attempts=NotificationOutbox.attempts + 1,
                )
                .returning(
                    NotificationOutbox.id,
                    NotificationOutbox.recipient,
                    NotificationOutbox.message,
                    NotificationOutbox.attempts,
                )
                .execution_options(synchronize_session=False)
            ).first()
            session.commit()
            if row is not None:
                return Delivery(row.id, row.recipient, row.message, row.attempts, token)
    return None


def finish_delivery(delivery: Delivery, accepted: bool, error: str | None = None) -> bool:
    now = _now()
    status = "sent" if accepted else "failed" if delivery.attempts >= MAX_ATTEMPTS else "pending"
    delay = RETRY_SECONDS[min(delivery.attempts - 1, len(RETRY_SECONDS) - 1)]
    with get_session() as session:
        result = session.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.id == delivery.id,
                NotificationOutbox.status == "sending",
                NotificationOutbox.lease_token == delivery.token,
            )
            .values(
                status=status,
                lease_token=None,
                accepted_at=now if accepted else None,
                available_at=now if accepted else now + timedelta(seconds=delay),
                last_error=None if accepted else error or "delivery_rejected",
            )
        )
        session.commit()
        changed = result.rowcount == 1
    if not changed:
        logger.warning("outbox bloqueo perdido id=%s", delivery.id)
    elif status == "failed":
        logger.error("outbox agotado id=%s attempts=%s", delivery.id, delivery.attempts)
    elif accepted:
        logger.info("outbox aceptado por Meta id=%s", delivery.id)
    else:
        logger.warning("outbox pendiente id=%s attempts=%s", delivery.id, delivery.attempts)
    return changed


def dispatch_pending(stop: Event | None = None, limit: int = 20) -> int:
    processed = 0
    while processed < limit and not (stop and stop.is_set()):
        delivery = claim_notification()
        if delivery is None:
            break
        try:
            accepted = send_text(delivery.recipient, delivery.message)
            error = None if accepted else "delivery_rejected"
        except Exception as exc:
            accepted, error = False, type(exc).__name__[:80]
            logger.warning(
                "outbox error id=%s wa_id_hash=%s", delivery.id, hash_wa_id(delivery.recipient)
            )
        # If this write fails, the persisted lease expires and another run can recover it.
        # Meta acceptance followed by a crash can still cause a duplicate: not exactly-once.
        finish_delivery(delivery, accepted, error)
        processed += 1
    return processed


def _dispatch_loop(stop: Event) -> None:
    while not stop.is_set():
        try:
            if dispatch_pending(stop) == 20:
                continue
        except Exception:
            logger.exception("outbox no disponible; se reintentara")
        stop.wait(POLL_SECONDS)


@contextmanager
def outbox_dispatcher():
    stop = Event()
    thread = Thread(target=_dispatch_loop, args=(stop,), name="notification-outbox", daemon=True)
    thread.start()
    logger.info("outbox activo interval=%ss", POLL_SECONDS)
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=40)
        if thread.is_alive():
            logger.warning("outbox terminando; los bloqueos pendientes se recuperaran al vencer")


def deliver_notification(recipient: str, message: str) -> None:
    """Compatibility for notification jobs already stored in RQ before this upgrade."""
    if not send_text(recipient, message):
        raise RuntimeError("WhatsApp rechazó la notificación")
