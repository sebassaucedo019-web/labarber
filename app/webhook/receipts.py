"""Delivery receipts and explicit reminder opt-out from signature-verified payloads."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.identity import normalize_phone, phone_aliases
from app.scheduling import audit, calendar_lock, invalidate_notices
from app.store.models import Appointment, MessagingPreference, NotificationOutbox
from app.store.postgres import get_session


def values(payload):
    entries = payload.get("entry", [])
    for entry in entries if isinstance(entries, list) else []:
        changes = entry.get("changes", []) if isinstance(entry, dict) else []
        for change in changes if isinstance(changes, list) else []:
            value = change.get("value") if isinstance(change, dict) else None
            if not isinstance(value, dict):
                continue
            metadata = value.get("metadata")
            if (
                isinstance(metadata, dict)
                and metadata.get("phone_number_id") == get_settings().whatsapp_phone_number_id
            ):
                yield value


def process_receipts(payload):
    for value in values(payload):
        statuses = value.get("statuses", [])
        for receipt in statuses if isinstance(statuses, list) else []:
            if not isinstance(receipt, dict):
                continue
            state, message_id = receipt.get("status"), receipt.get("id")
            if state not in {"sent", "delivered", "read", "failed"} or not isinstance(
                message_id, str
            ):
                continue
            callback = receipt.get("biz_opaque_callback_data", "")
            try:
                prefix, identity, event_id = callback.split(":")
                if prefix != "waia" or not identity.isdigit() or len(event_id) != 32:
                    continue
                timestamp = datetime.fromtimestamp(int(receipt["timestamp"]), UTC).replace(
                    tzinfo=None
                )
                if timestamp > datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5):
                    continue
            except (AttributeError, KeyError, ValueError, TypeError, OverflowError, OSError):
                continue
            with get_session() as session:
                calendar_lock(session)
                row = session.scalar(
                    select(NotificationOutbox)
                    .where(
                        NotificationOutbox.id == int(identity),
                        NotificationOutbox.event_id == event_id,
                        NotificationOutbox.kind != "appointment",
                    )
                    .with_for_update()
                )
                if (
                    row is None
                    or normalize_phone(receipt.get("recipient_id")) != row.recipient
                    or (row.provider_message_id and row.provider_message_id != message_id)
                ):
                    continue
                # Ignore callbacks for a message that never had a submission attempt.
                if row.attempts < 1:
                    continue
                row.provider_message_id = message_id
                rank = {"sent": 1, "failed": 1, "delivered": 2, "read": 3}
                if rank.get(row.status, 0) > rank[state] or (
                    row.status == "failed" and state == "sent"
                ):
                    continue
                row.status, row.lease_token = state, None
                if state == "sent":
                    row.accepted_at = row.accepted_at or timestamp
                elif state in {"delivered", "read"}:
                    row.delivered_at = row.delivered_at or timestamp
                    row.last_error = None
                    if state == "read":
                        row.read_at = row.read_at or timestamp
                else:
                    errors = receipt.get("errors", [])
                    code = (
                        errors[0].get("code")
                        if isinstance(errors, list) and errors and isinstance(errors[0], dict)
                        else None
                    )
                    row.last_error = (
                        f"meta_delivery_{code}"[:80]
                        if isinstance(code, int)
                        else "meta_delivery_failed"
                    )
                session.commit()


def process_opt_out(payload):
    for value in values(payload):
        messages = value.get("messages", [])
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict) or message.get("type") != "text":
                continue
            body = message.get("text", {})
            body = body.get("body") if isinstance(body, dict) else None
            if not isinstance(body, str) or body.strip().casefold() not in {
                "stop",
                "baja",
                "no recordatorios",
                "no quiero recordatorios",
                "alta recordatorios",
            }:
                continue
            phone = normalize_phone(message.get("from"))
            if not phone:
                continue
            with get_session() as session:
                calendar_lock(session)
                pref = session.get(MessagingPreference, phone)
                if pref is None:
                    pref = MessagingPreference(wa_id=phone)
                    session.add(pref)
                pref.opted_out = body.strip().casefold() != "alta recordatorios"
                if not pref.opted_out:
                    audit(
                        session,
                        None,
                        "customer",
                        "reminders_opt_in",
                        "Nueva autorización desde WhatsApp",
                    )
                    session.commit()
                    continue
                rows = session.scalars(
                    select(Appointment).where(Appointment.wa_id.in_(phone_aliases(phone)))
                ).all()
                for row in rows:
                    if row.reminder_consent:
                        row.reminder_consent = False
                        audit(session, row.id, "customer", "opt_out")
                    invalidate_notices(session, row.id)
                session.commit()
