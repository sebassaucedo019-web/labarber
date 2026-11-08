from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.retention import purge_history
from app.store.models import Appointment, Base, Conversation, MessageLog, PendingAction


def test_retention_dry_run_then_apply_preserves_citas_recent_and_pending():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime(2026, 11, 7, 18, tzinfo=UTC)
    old = now - timedelta(days=91)
    with Session(engine) as db:
        db.add_all(
            [
                Conversation(wa_id="525500000001", history_json="old", updated_at=old),
                Conversation(wa_id="525500000002", history_json="recent", updated_at=now),
                Conversation(wa_id="525500000003", history_json="pending", updated_at=old),
                PendingAction(
                    wa_id="525500000003",
                    action="cancel",
                    payload="{}",
                    turn_id="1",
                    expires_at=datetime(2026, 11, 7, 12, 10),
                ),
                MessageLog(wa_id_hash="old-hash", direction="in", content="old", created_at=old),
                MessageLog(wa_id_hash="recent-hash", direction="in", content="new", created_at=now),
                Appointment(
                    wa_id="525500000001",
                    customer_name="Ana",
                    service="corte normal",
                    barber="Obed",
                    starts_at=datetime(2026, 11, 8, 12),
                ),
            ]
        )
        db.commit()
        counts = purge_history(db, 90, now=now)
        assert counts == {"dry_run": True, "days": 90, "message_logs": 1, "conversations": 1}
        assert db.get(Conversation, "525500000001") is not None
        purge_history(db, 90, apply=True, now=now)
        db.expire_all()
        assert db.get(Conversation, "525500000001") is None
        assert db.get(Conversation, "525500000002") is not None
        assert db.get(Conversation, "525500000003") is not None
        assert len(db.scalars(select(MessageLog)).all()) == 1
        assert db.scalar(select(Appointment)).customer_name == "Ana"
    engine.dispose()
