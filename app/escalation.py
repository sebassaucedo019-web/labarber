import logging
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.observability import hash_wa_id

logger = logging.getLogger(__name__)


def notify_human(wa_id: str, motivo: str) -> None:
    """Avisa a un humano que hay que tomar esta conversación, vía ESCALATION_WEBHOOK_URL.
    Sin esa variable configurada, no rompe el flujo del bot pero tampoco avisa a nadie —
    se loguea como warning para que no pase desapercibido. Ver docs/08-escalado-a-humano.md."""
    webhook_url = get_settings().escalation_webhook_url
    if not webhook_url:
        logger.warning(
            "escalado sin ESCALATION_WEBHOOK_URL configurada, nadie fue notificado "
            "wa_id_hash=%s motivo=%s",
            hash_wa_id(wa_id),
            motivo,
        )
        return
    payload = _build_payload(wa_id, motivo, webhook_url)
    try:
        httpx.post(webhook_url, json=payload, timeout=5)
    except httpx.HTTPError:
        logger.exception(
            "no se pudo notificar el escalado a humano wa_id_hash=%s", hash_wa_id(wa_id)
        )


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
