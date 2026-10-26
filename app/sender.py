import logging

import httpx
from pywa import WhatsApp

from app.agenda import staff_scope
from app.config import get_settings
from app.identity import normalize_phone
from app.observability import hash_wa_id
from app.safety import sanitize_reply

logger = logging.getLogger(__name__)

_client: WhatsApp | None = None


def _meta_recipient_id(wa_id: str) -> str:
    """Convert Mexican local and legacy IDs to Meta's international format."""
    recipient = normalize_phone(wa_id)
    if recipient is None:
        raise ValueError("Número de WhatsApp inválido")
    return recipient


def get_client() -> WhatsApp:
    global _client
    if _client is None:
        settings = get_settings()
        _client = WhatsApp(
            phone_id=settings.whatsapp_phone_number_id,
            token=settings.whatsapp_access_token,
            session=httpx.Client(timeout=10),
        )
    return _client


def send_text(wa_id: str, text: str) -> bool:
    try:
        recipient = _meta_recipient_id(wa_id)
        logger.info("enviando respuesta a Meta wa_id_hash=%s", hash_wa_id(wa_id))
        sent = get_client().send_message(to=recipient, text=sanitize_reply(text)[:4096])
        logger.info(
            "respuesta enviada a WhatsApp wa_id_hash=%s message_id=%s",
            hash_wa_id(wa_id),
            getattr(sent, "id", "desconocido"),
        )
        return True
    except Exception:
        logger.exception(
            "no se pudo enviar el mensaje wa_id_hash=%s",
            hash_wa_id(wa_id),
        )
        return False


def welcome_menu_content(wa_id: str) -> tuple[str, list[tuple[str, str]]]:
    scope = staff_scope(wa_id)
    if scope is not None:
        body = (
            "Hola. Panel del equipo de BARBER CG.\nPuedes consultar la agenda general y cancelar citas."
            if scope == "all"
            else f"Hola, {scope}. Panel del equipo de BARBER CG.\n"
            "Puedes consultar tu agenda y cancelar las citas asignadas a ti."
        )
        return body, [
            ("staff_agenda", "Agenda general" if scope == "all" else "Mi agenda"),
            ("staff_next", "Siguiente cita"),
            ("staff_cancel", "Cancelar cita"),
        ]
    return (
        "¡Hola! Bienvenido a BARBER CG 💈\n\nSoy el asistente de la barbería. ¿Qué necesitas?",
        [("services", "Servicios"), ("book", "Agendar"), ("my_appointment", "Mi cita")],
    )


def welcome_menu_text(wa_id: str) -> str:
    """Keep text fallback and conversation history aligned with the actual menu."""
    body, buttons = welcome_menu_content(wa_id)
    return body + "\nOpciones: " + ", ".join(title for _, title in buttons) + "."


def send_welcome_buttons(wa_id: str) -> bool:
    """Send the first-message menu; fall back to text if Meta rejects it."""
    settings = get_settings()
    recipient = _meta_recipient_id(wa_id)
    body, buttons = welcome_menu_content(wa_id)
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": button_id, "title": title}}
                    for button_id, title in buttons
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
        return True
    except Exception:
        logger.exception("no se pudo enviar el menú inicial; se usa texto")
        return send_text(wa_id, welcome_menu_text(wa_id))
