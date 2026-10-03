import logging

from pywa import WhatsApp

from app.config import get_settings
from app.observability import hash_wa_id

logger = logging.getLogger(__name__)

_client: WhatsApp | None = None


def get_client() -> WhatsApp:
    global _client
    if _client is None:
        settings = get_settings()
        _client = WhatsApp(
            phone_id=settings.whatsapp_phone_number_id,
            token=settings.whatsapp_access_token,
        )
    return _client


def send_text(wa_id: str, text: str) -> None:
    try:
        get_client().send_message(to=wa_id, text=text)
    except Exception:
        logger.exception(
            "no se pudo enviar el mensaje wa_id_hash=%s — si el error es de ventana, "
            "revisá docs/01-arquitectura.md (regla de las 24h, necesitás una plantilla)",
            hash_wa_id(wa_id),
        )
