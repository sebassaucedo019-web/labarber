"""Operator-only retention of old conversations/logs. Dry run unless --apply is passed."""

import argparse
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, exists, func, select

from app.store.calendar_time import BUSINESS_TZ
from app.store.models import Conversation, MessageLog, PendingAction


def purge_history(session, days: int, *, apply: bool = False, now: datetime | None = None):
    if not 1 <= days <= 3650:
        raise ValueError("El plazo debe estar entre 1 y 3650 días")
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("La hora debe incluir zona horaria")
    cutoff = now.astimezone(UTC) - timedelta(days=days)
    local = now.astimezone(BUSINESS_TZ).replace(tzinfo=None)
    filters = {
        "message_logs": (MessageLog, MessageLog.created_at < cutoff),
        "conversations": (
            Conversation,
            (Conversation.updated_at < cutoff)
            & ~exists().where(
                PendingAction.wa_id == Conversation.wa_id, PendingAction.expires_at > local
            ),
        ),
    }
    result = {"dry_run": not apply, "days": days}
    for label, (model, condition) in filters.items():
        result[label] = session.scalar(select(func.count()).select_from(model).where(condition))
        if apply:
            session.execute(delete(model).where(condition))
    if apply:
        session.commit()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from app.store.postgres import get_session

    with get_session() as session:
        print(json.dumps(purge_history(session, args.days, apply=args.apply)))


if __name__ == "__main__":
    main()
