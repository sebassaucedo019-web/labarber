from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass
class BotDeps:
    wa_id: str
    db: Session
    menu_sent: bool = False
