import logging
import re
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from redis.exceptions import WatchError

from app.config import get_settings
from app.identity import normalize_phone
from app.observability import hash_wa_id
from app.scope import _normalize
from app.store.redis_store import decode, get_redis

logger = logging.getLogger(__name__)

_REAL_ESCALATION_RE = re.compile(
    r"\b(?:hablar con (?:una |un |el |la )?(?:persona|humano|alguien|dueno|encargado|jesus|obed|yadier)|"
    r"(?:pasame|comunicame) con (?:el |la )?(?:dueno|encargado|jesus|obed|yadier)|"
    r"persona del equipo|queja|reclamo|"
    r"problema con (?:mi )?(?:cita|reserva|pago)|cobro incorrecto|"
    r"(?:no funciona|error) (?:con|en) (?:la )?(?:cita|reserva|barberia|bot|pago))\b",
    re.IGNORECASE,
)


def is_support_request(text: str) -> bool:
    return bool(_REAL_ESCALATION_RE.search(_normalize(text)))


def _finish_notice(dedupe_key: str, token: str, notified: bool) -> None:
    redis = get_redis()
    while True:
        with redis.pipeline() as pipe:
            try:
                pipe.watch(dedupe_key)
                if decode(pipe.get(dedupe_key)) != token:
                    return
                pipe.multi()
                if notified:
                    pipe.set(dedupe_key, "sent", ex=300)
                else:
                    pipe.delete(dedupe_key)
                pipe.execute()
                return
            except WatchError:
                continue


def notify_human(wa_id: str, motivo: str) -> bool:
    """Avisa al dueño por WhatsApp y, opcionalmente, a un webhook externo."""
    if not is_support_request(motivo):
        logger.info("escalado omitido: no es una solicitud de soporte real")
        return False
    wa_id = normalize_phone(wa_id)
    if wa_id is None:
        return False
    settings = get_settings()
    redis = get_redis()
    dedupe_key = f"escalated:{hash_wa_id(wa_id)}"
    token = f"pending:{uuid4().hex}"
    if not redis.set(dedupe_key, token, nx=True, ex=60):
        return decode(redis.get(dedupe_key)) == "sent"
    notified = False
    try:
        if settings.owner_wa_id:
            from app.sender import send_text

            notified = send_text(
                settings.owner_wa_id,
                f"Escalado de BARBER CG 💈\nCliente: {wa_id}\nMotivo: {motivo}",
            )
        webhook_url = settings.escalation_webhook_url
        if webhook_url:
            payload = _build_payload(wa_id, motivo, webhook_url)
            try:
                response = httpx.post(webhook_url, json=payload, timeout=5)
                response.raise_for_status()
                notified = True
            except httpx.HTTPError:
                logger.exception(
                    "no se pudo notificar el escalado a humano wa_id_hash=%s", hash_wa_id(wa_id)
                )
        elif not notified:
            logger.warning("escalado no entregado wa_id_hash=%s", hash_wa_id(wa_id))
        return notified
    finally:
        try:
            _finish_notice(dedupe_key, token, notified)
        except Exception:
            # A bookkeeping failure must not contradict an accepted delivery.
            logger.exception("no se guardó el estado del aviso wa_id_hash=%s", hash_wa_id(wa_id))


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
