import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

import httpx
from redis.exceptions import WatchError

from app.config import get_settings
from app.identity import normalize_phone
from app.observability import hash_wa_id
from app.store.redis_store import decode, get_redis

logger = logging.getLogger(__name__)

NoticeStatus = Literal["sent", "recent", "pending", "failed", "unavailable", "self"]


def _destination(target: str) -> str | None:
    settings = get_settings()
    return normalize_phone(
        {
            "owner": settings.owner_wa_id,
            "Obed": settings.barber_obed_wa_id,
            "Jesús": settings.barber_jesus_wa_id,
            "Yadier": settings.barber_yadier_wa_id,
        }.get(target)
    )


def _notice_key(wa_id: str, target: str = "owner") -> str:
    destination = _destination(target)
    recipient_key = hash_wa_id(destination) if destination else "owner-webhook"
    return f"escalated:v2:{hash_wa_id(normalize_phone(wa_id) or wa_id)}:{recipient_key}"


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


def notify_human(wa_id: str, motivo: str, *, target: str = "owner") -> NoticeStatus:
    """Transport for an already reviewed request; target is a configured staff identity."""
    if target not in {"owner", "Obed", "Jesús", "Yadier"}:
        return "unavailable"
    wa_id = normalize_phone(wa_id)
    if wa_id is None or not motivo.strip():
        return "failed"
    settings = get_settings()
    recipient = _destination(target)
    # A generic webhook is not proof that the named barber was notified.
    webhook_url = settings.escalation_webhook_url if target == "owner" else None
    if recipient == wa_id:
        return "self"
    if not recipient and not webhook_url:
        return "unavailable"
    redis = get_redis()
    dedupe_key = _notice_key(wa_id, target)
    token = f"pending:{uuid4().hex}"
    if not redis.set(dedupe_key, token, nx=True, ex=60):
        return "recent" if decode(redis.get(dedupe_key)) == "sent" else "pending"
    notified = False
    try:
        if recipient:
            from app.sender import send_text

            notified = send_text(
                recipient,
                f"Solicitud de atención en BARBER CG\nCliente: +{wa_id}\n"
                f"Para: {'el equipo' if target == 'owner' else target}\n"
                f"Mensaje del cliente: {motivo[:1000]}",
            )
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
        return "sent" if notified else "failed"
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
