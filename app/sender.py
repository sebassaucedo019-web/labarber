import logging

import httpx
from pywa import WhatsApp

from app.config import get_settings
from app.observability import hash_wa_id

logger = logging.getLogger(__name__)

_client: WhatsApp | None = None


def _meta_recipient_id(wa_id: str) -> str:
    """Convert Mexican local and legacy IDs to Meta's international format."""
    digits = "".join(ch for ch in wa_id if ch.isdigit())
    if digits.startswith("521") and len(digits) == 13:
        return "52" + digits[3:]
    if len(digits) == 10:
        return "52" + digits
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


def send_welcome_buttons(wa_id: str) -> None:
    """Send the first-message menu; fall back to text if Meta rejects it."""
    settings = get_settings()
    recipient = _meta_recipient_id(wa_id)
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    "¡Hola! Bienvenido a BARBER CG 💈\n\n"
                    "Soy el asistente de la barbería. ¿Qué necesitas?"
                )
            },
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "services", "title": "Ver servicios"}},
                    {"type": "reply", "reply": {"id": "book", "title": "Agendar cita"}},
                    {"type": "reply", "reply": {"id": "my_appointment", "title": "Consultar mi cita"}},
                ]
            },
        },
    }
    try:
        response = httpx.post(
            f"https://graph.facebook.com/v25.0/{settings.whatsapp_phone_number_id}/messages",
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token}"},
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
        logger.info("menú inicial enviado a WhatsApp wa_id_hash=%s", hash_wa_id(wa_id))
    except Exception:
        logger.exception("no se pudo enviar el menú inicial; se usa texto")
        send_text(
            wa_id,
            "¡Hola! Bienvenido a BARBER CG 💈\n\n"
            "¿Qué necesitas? Puedes decirme: ver servicios, agendar cita o consultar mi cita.",
        )
