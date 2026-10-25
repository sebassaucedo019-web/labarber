import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.agent.deps import BotDeps
from app.identity import normalize_phone
from app.scope import _normalize
from app.store.models import PendingAction

_CONFIRMATION = re.compile(
    r"^(?:si+(?:\s+confirmo)?|sip|simon|confirmo(?:\s+la\s+cita)?|va|dale|adelante|"
    r"ok(?:ay)?|hazlo|agendala|cancelala|confirmar)(?:\s+(?:por\s+favor|porfa|gracias))?$"
)


def confirm_action(deps: BotDeps, action: str, payload: dict, summary: str) -> bool:
    """A model cannot confirm its own proposal within the same turn."""
    wa_id = normalize_phone(deps.wa_id) or deps.wa_id
    now = datetime.now(ZoneInfo("America/Chihuahua")).replace(tzinfo=None)
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    confirmation_text = " ".join(re.sub(r"[¡!.,]", " ", _normalize(deps.user_message)).split())
    row = deps.db.get(PendingAction, wa_id)
    if (
        row is not None
        and row.expires_at > now
        and row.turn_id != deps.turn_id
        and row.action == action
        and row.payload == serialized
        and _CONFIRMATION.fullmatch(confirmation_text)
    ):
        deps.db.delete(row)
        deps.pending_action_reply = None
        return True
    if row is None:
        row = PendingAction(wa_id=wa_id)
        deps.db.add(row)
    row.action = action
    row.payload = serialized
    row.turn_id = deps.turn_id
    row.expires_at = now + timedelta(minutes=15)
    deps.db.commit()
    deps.pending_action_reply = f"{summary}\n¿Confirmas? Responde sí o confirmo."
    return False
