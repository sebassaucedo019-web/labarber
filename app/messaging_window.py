"""Per-recipient WhatsApp service windows from signature-verified customer messages."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.identity import normalize_phone
from app.store.models import CustomerWindow
from app.store.postgres import get_session
from app.webhook.receipts import message_time, values


def process_customer_windows(payload):
    now = datetime.now(UTC).replace(tzinfo=None)
    latest = {}
    for value in values(payload):
        messages = value.get("messages", [])
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict) or not message.get("id"):
                continue
            sender = normalize_phone(message.get("from"))
            at = message_time(message.get("timestamp"))
            if sender is None or at is None or at > now:
                continue
            latest[sender] = max(at, latest.get(sender, at))
    if not latest:
        return
    with get_session() as session:
        insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
        for sender, at in latest.items():
            statement = insert(CustomerWindow).values(wa_id=sender, last_message_at=at)
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[CustomerWindow.wa_id],
                    set_={"last_message_at": at},
                    where=CustomerWindow.last_message_at < at,
                )
            )
        session.commit()


def window_is_open(recipient: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC).replace(tzinfo=None)
    with get_session() as session:
        row = session.get(CustomerWindow, normalize_phone(recipient))
        return row is not None and timedelta(0) <= now - row.last_message_at < timedelta(hours=24)
