from __future__ import annotations

import asyncio
import logging

from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy.orm import Session

from app.agent.agent import get_agent
from app.agent.deps import BotDeps
from app.observability import check_rate_limit, hash_wa_id
from app.queue.debounce import schedule_processing
from app.queue.dedupe import already_processed
from app.sender import send_text
from app.store.postgres import get_session, load_history, log_message, save_history
from app.store.redis_store import pop_pending_messages, push_pending_message

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 25
FALLBACK_REPLY = "Dame un segundo que lo estoy pensando, ya te respondo 🙂"


def buffer_inbound(wa_id: str, message_id: str, text: str) -> None:
    """Job rápido: guarda el mensaje y reprograma el debounce. Lo dispara el webhook."""
    if already_processed(message_id):
        logger.info("mensaje duplicado ignorado wa_id_hash=%s", hash_wa_id(wa_id))
        return
    push_pending_message(wa_id, text)
    schedule_processing(wa_id)


def process_wa_id(wa_id: str) -> None:
    """Job que dispara el debounce: junta los mensajes pendientes y corre el agente."""
    if not check_rate_limit(wa_id):
        logger.warning("rate limit excedido wa_id_hash=%s", hash_wa_id(wa_id))
        return

    messages = pop_pending_messages(wa_id)
    if not messages:
        return

    prompt = "\n".join(messages)
    session = get_session()
    try:
        log_message(session, wa_id, "in", prompt)
        reply = _run_agent(session, wa_id, prompt)
        log_message(session, wa_id, "out", reply)
    finally:
        session.close()

    send_text(wa_id, reply)


def _run_agent(session: Session, wa_id: str, prompt: str) -> str:
    try:
        raw_history = load_history(session, wa_id)
        history = ModelMessagesTypeAdapter.validate_json(raw_history) if raw_history else []
        deps = BotDeps(wa_id=wa_id, db=session)
        result = asyncio.run(
            asyncio.wait_for(
                get_agent().run(prompt, deps=deps, message_history=history),
                timeout=LLM_TIMEOUT_SECONDS,
            )
        )
        save_history(session, wa_id, result.all_messages_json())
        return str(result.output)
    except TimeoutError:
        logger.warning("timeout del LLM wa_id_hash=%s", hash_wa_id(wa_id))
        return FALLBACK_REPLY
    except Exception:
        logger.exception("error corriendo el agente wa_id_hash=%s", hash_wa_id(wa_id))
        return FALLBACK_REPLY
