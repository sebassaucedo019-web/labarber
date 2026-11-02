"""Persistent reminders reconciled from appointments, never an in-memory timer per booking."""

import hashlib
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import exists, select, update

from app.config import get_settings
from app.identity import normalize_phone
from app.scheduling import calendar_lock, local_now
from app.store.models import Appointment, MessagingPreference, NotificationOutbox
from app.store.postgres import get_session


def notice_key(row):
    value = (
        f"arrival:{row.id}:{row.starts_at.isoformat()}:{row.barber}:{normalize_phone(row.wa_id)}"
    )
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def eligible(session, row, now):
    if row.status != "confirmed" or row.arrived_at or not row.reminder_consent:
        return False
    if not normalize_phone(row.wa_id) or not row.barber:
        return False
    preference = session.get(MessagingPreference, normalize_phone(row.wa_id))
    return not (preference and preference.opted_out) and timedelta(
        0
    ) <= row.starts_at - now <= timedelta(minutes=30)


def stage_notice(session, row, kind, now):
    if not eligible(session, row, now):
        return None
    if kind == "reminder":
        # A new/changed booking inside 30 minutes already has its confirmation.
        if row.starts_at - now < timedelta(minutes=5):
            return None
        if row.schedule_updated_at and row.starts_at - row.schedule_updated_at < timedelta(
            minutes=30
        ):
            return None
    event_id = notice_key(row)
    existing = session.scalar(
        select(NotificationOutbox).where(
            NotificationOutbox.event_id == event_id,
            NotificationOutbox.recipient == normalize_phone(row.wa_id),
        )
    )
    if existing:
        return existing
    # Suppress an equivalent accepted/in-flight notice after a last-minute move too.
    utc_now = datetime.now(UTC).replace(tzinfo=None)
    recent = session.scalar(
        select(NotificationOutbox.id)
        .where(
            NotificationOutbox.appointment_id == row.id,
            NotificationOutbox.kind.in_(("reminder", "next_turn")),
            NotificationOutbox.status.in_(("sending", "sent", "delivered", "read", "uncertain")),
            NotificationOutbox.created_at >= utc_now - timedelta(minutes=30),
        )
        .limit(1)
    )
    if recent:
        return None
    business = get_settings().business_name
    message = f"Hola, {row.customer_name}. Tu cita en {business} está próxima, a las {row.starts_at:%H:%M}."
    if kind == "next_turn":
        message += " Tu barbero ya terminó su servicio anterior."
    message += " ¡Te esperamos!"
    notification = NotificationOutbox(
        appointment_id=row.id,
        event_id=event_id,
        recipient=normalize_phone(row.wa_id),
        message=message,
        kind=kind,
        scheduled_start=row.starts_at,
        scheduled_barber=row.barber,
        available_at=utc_now,
    )
    session.add(notification)
    session.flush()
    return notification


def reconcile_reminders(now=None):
    now = now or local_now()
    with get_session() as session:
        calendar_lock(session)
        valid = exists().where(
            Appointment.id == NotificationOutbox.appointment_id,
            Appointment.status == "confirmed",
            Appointment.reminder_consent.is_(True),
            Appointment.arrived_at.is_(None),
            Appointment.starts_at >= now,
            Appointment.starts_at == NotificationOutbox.scheduled_start,
            Appointment.barber == NotificationOutbox.scheduled_barber,
        )
        session.execute(
            update(NotificationOutbox)
            .where(
                NotificationOutbox.kind != "appointment",
                NotificationOutbox.status == "pending",
                ~valid,
            )
            .values(status="cancelled", last_error="no_longer_relevant")
        )
        rows = session.scalars(
            select(Appointment)
            .where(
                Appointment.status == "confirmed",
                Appointment.reminder_consent.is_(True),
                Appointment.starts_at >= now + timedelta(minutes=5),
                Appointment.starts_at <= now + timedelta(minutes=30),
            )
            .order_by(Appointment.starts_at)
        ).all()
        for row in rows:
            stage_notice(session, row, "reminder", now)
        session.commit()


def send_template_notice(notice, appointment):
    """Use approved utility templates even inside the customer-service window.

    The exact body must be approved in Meta; positional body params are name,
    business and booked local time. No fallback to unsolicited free-form text.
    """
    settings = get_settings()
    template = (
        settings.turn_template_name
        if notice.kind == "next_turn"
        else settings.reminder_template_name
    )
    if not template:
        return "failed", None, "template_not_configured"
    payload = {
        "messaging_product": "whatsapp",
        "to": notice.recipient,
        "type": "template",
        "biz_opaque_callback_data": f"waia:{notice.id}:{notice.event_id}",
        "template": {
            "name": template,
            "language": {"code": settings.notification_template_language},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": value}
                        for value in (
                            appointment.customer_name,
                            settings.business_name,
                            f"{appointment.starts_at:%H:%M}",
                        )
                    ],
                }
            ],
        },
    }
    try:
        response = httpx.post(
            f"https://graph.facebook.com/v25.0/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            json=payload,
            timeout=10,
        )
    except httpx.TransportError:
        return "uncertain", None, "transport_outcome_unknown"
    if response.status_code >= 400:
        retryable = response.status_code == 429 or response.status_code >= 500
        return "pending" if retryable else "failed", None, f"meta_http_{response.status_code}"
    try:
        message_id = response.json()["messages"][0]["id"]
        if not isinstance(message_id, str) or not message_id:
            raise ValueError("missing id")
    except (ValueError, KeyError, IndexError, TypeError):
        return "uncertain", None, "acceptance_without_id"
    return "sent", message_id, None


def dispatch_automatic(delivery):
    from app.notifications import MAX_ATTEMPTS, RETRY_SECONDS, _now
    from app.scheduling import calendar_lock

    with get_session() as session:
        calendar_lock(session)
        # Serialize cancellation/rescheduling and state changes with validation + submission.
        notice = session.scalar(
            select(NotificationOutbox)
            .where(
                NotificationOutbox.id == delivery.id,
                NotificationOutbox.lease_token == delivery.token,
                NotificationOutbox.status == "sending",
            )
            .with_for_update()
        )
        if notice is None:
            return
        row = session.scalar(
            select(Appointment).where(Appointment.id == notice.appointment_id).with_for_update()
        )
        now = local_now()
        if not get_settings().automatic_notices_enabled:
            notice.status, notice.last_error = "pending", "disabled"
        elif (
            row is None
            or row.starts_at != notice.scheduled_start
            or row.barber != notice.scheduled_barber
            or normalize_phone(row.wa_id) != notice.recipient
            or not eligible(session, row, now)
            or (notice.kind == "reminder" and row.starts_at - now < timedelta(minutes=5))
        ):
            notice.status, notice.last_error = "cancelled", "no_longer_relevant"
        else:
            status, message_id, error = send_template_notice(notice, row)
            notice.status = (
                "failed" if status == "pending" and notice.attempts >= MAX_ATTEMPTS else status
            )
            notice.provider_message_id = message_id
            notice.last_error = error
            if status == "sent":
                notice.accepted_at = _now()
        notice.lease_token = None
        if notice.status == "pending":
            delay = RETRY_SECONDS[min(max(notice.attempts - 1, 0), len(RETRY_SECONDS) - 1)]
            notice.available_at = _now() + timedelta(seconds=delay)
        session.commit()
