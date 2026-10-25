"""Notifications must not turn a committed booking into an apparent failure."""

import logging

from rq import Retry

from app.observability import hash_wa_id
from app.queue.client import get_queue
from app.sender import send_text

logger = logging.getLogger(__name__)


def deliver_notification(recipient: str, message: str) -> None:
    if not send_text(recipient, message):
        raise RuntimeError("WhatsApp rechazó la notificación")


def notify(recipient: str, message: str) -> None:
    try:
        get_queue().enqueue(
            deliver_notification,
            recipient,
            message,
            retry=Retry(max=3, interval=[15, 60, 300]),
            job_timeout=30,
            description=f"notification:{hash_wa_id(recipient)}",
        )
    except Exception:
        logger.exception("no se pudo encolar notificación wa_id_hash=%s", hash_wa_id(recipient))
        if not send_text(recipient, message):
            logger.error("notificación no entregada wa_id_hash=%s", hash_wa_id(recipient))
