import logging
import re
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.observability import hash_wa_id

logger = logging.getLogger(__name__)

_REAL_ESCALATION_RE = re.compile(
    r"\b(?:hablar con (?:una )?(?:persona|humano|alguien|el dueño|el encargado)|"
    r"persona del equipo|dueño|encargado|queja|reclamo|no funciona|error|"
    r"problema con (?:mi )?(?:cita|reserva|pago)|cobro incorrecto)\b",
    re.IGNORECASE,
)


def notify_human(wa_id: str, motivo: str) -> bool:
    """Avisa al dueño por WhatsApp y, opcionalmente, a un webhook externo."""
    if not _REAL_ESCALATION_RE.search(motivo):
        logger.info("escalado omitido: no es una solicitud de soporte real")
        return False
    settings = get_settings()
    notified = False
    if settings.owner_wa_id:
        from app.sender import send_text

        notified = send_text(
            settings.owner_wa_id,
            f"Escalado de BARBER CG 💈\nCliente: {wa_id}\nMotivo: {motivo}",
        )
    webhook_url = settings.escalation_webhook_url
    if not webhook_url:
        logger.warning(
            "escalado sin ESCALATION_WEBHOOK_URL configurada; whatsapp_notificado=%s "
            "wa_id_hash=%s motivo=%s",
            notified,
            hash_wa_id(wa_id),
            motivo,
        )
        return notified
    payload = _build_payload(wa_id, motivo, webhook_url)
    try:
        response = httpx.post(webhook_url, json=payload, timeout=5)
        response.raise_for_status()
        notified = True
    except httpx.HTTPError:
        logger.exception(
            "no se pudo notificar el escalado a humano wa_id_hash=%s", hash_wa_id(wa_id)
        )
    return notified


def _build_payload(wa_id: str, motivo: str, webhook_url: str) -> dict[str, str]:
    """Slack y Discord no aceptan cualquier JSON en su webhook — esperan un campo
    puntual (`text` / `content`). Si la URL es de uno de los dos, la pegás tal cual acá
    y armamos el shape correcto. Para cualquier otro destino (n8n, Zapier, tu propio
    endpoint) mandamos el evento genérico, que sí puede parsear lo que sea."""
    mensaje = f"Escalado de WhatsApp — motivo: {motivo} (wa_id: {wa_id})"
    if "hooks.slack.com" in webhook_url:
        return {"text": mensaje}
    if "discord.com/api/webhooks" in webhook_url:
        return {"content": mensaje}
    return {"wa_id": wa_id, "motivo": motivo, "timestamp": datetime.now(UTC).isoformat()}
