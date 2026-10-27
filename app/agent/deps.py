from dataclasses import dataclass, field
from uuid import uuid4

from sqlalchemy.orm import Session

from app.agent.support import SupportDecision


@dataclass
class BotDeps:
    wa_id: str
    db: Session
    menu_sent: bool = False
    user_message: str = ""
    completed_actions: list[str] = field(default_factory=list)
    turn_id: str = field(default_factory=lambda: uuid4().hex)
    pending_action_reply: str | None = None
    support_context: str = ""
    support_reviewed: bool = False
    support_decision: SupportDecision | None = None
    support_reply: str | None = None
