"""Authenticated queue notices: customer text cannot forge internal control messages."""

import hashlib
import hmac
import json

from app.config import get_settings

PREFIX = "__BARBER_QUEUE_NOTICE_V1__:"
MEDIA_REPLY = (
    "Por ahora puedo ayudarte por texto. No puedo interpretar ese archivo, audio o ubicación. "
    "Escríbeme qué necesitas de la barbería."
)
LIMIT_REPLY = "Recibí muchos mensajes seguidos. Espera un minuto y vuelve a escribir tu solicitud."
NOTICES = {"media": MEDIA_REPLY, "limit": LIMIT_REPLY}


def encode_notice(wa_id: str, kind: str) -> str:
    if kind not in NOTICES:
        raise ValueError("Unknown queue notice")
    body = json.dumps([wa_id, kind], separators=(",", ":"))
    signature = hmac.new(get_settings().meta_app_secret.encode(), body.encode(), hashlib.sha256)
    return PREFIX + signature.hexdigest() + ":" + body


def decode_notice(wa_id: str, value: str) -> str | None:
    if not value.startswith(PREFIX):
        return None
    signature, _, body = value[len(PREFIX) :].partition(":")
    expected = hmac.new(get_settings().meta_app_secret.encode(), body.encode(), hashlib.sha256)
    if not hmac.compare_digest(signature.encode(), expected.hexdigest().encode()):
        return None
    try:
        recipient, kind = json.loads(body)
    except (TypeError, ValueError):
        return None
    return NOTICES.get(kind) if recipient == wa_id and isinstance(kind, str) else None
