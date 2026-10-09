import logging

from pywa import WhatsApp

from app.config import get_settings
from app.observability import hash_wa_id

logger = logging.getLogger(__name__)

_client: WhatsApp | None = None


def _meta_recipient_id(wa_id: str) -> str:
    """Convert WhatsApp's legacy Mexico mobile format to Meta's API format."""
    digits = "".join(ch for ch in wa_id if ch.isdigit())
    if digits.startswith("521") and len(digits) == 13:
        return "52" + digits[3:]
    return digits


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
        recipient = _meta_recipient_id(wa_id)
        logger.info("enviando respuesta a Meta recipient=%s", recipient)
        sent = get_client().send_message(to=recipient, text=text)
        logger.info(
            "respuesta enviada a WhatsApp wa_id_hash=%s message_id=%s",
            hash_wa_id(wa_id),
            getattr(sent, "id", "desconocido"),
        )
    except Exception:
        logger.exception(
            "no se pudo enviar el mensaje recipient=%s wa_id_hash=%s",
            _meta_recipient_id(wa_id),
            hash_wa_id(wa_id),
        )
