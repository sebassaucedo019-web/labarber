from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic_ai.messages import ModelMessagesTypeAdapter
from sqlalchemy.orm import Session

from app.agent.agent import get_agent
from app.agent.deps import BotDeps
from app.agenda import agenda_link_message, is_agenda_link_request
from app.observability import check_rate_limit, hash_wa_id
from app.queue.debounce import schedule_processing
from app.queue.dedupe import already_processed
from app.sender import send_text, send_welcome_buttons
from app.safety import sanitize_reply
from app.scope import is_business_message, is_greeting
from app.store.postgres import get_session, load_history, log_message, save_history
from app.store.redis_store import pop_pending_messages, push_pending_message

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 25
FALLBACK_REPLY = "Dame un segundo que lo estoy pensando, ya te respondo 🙂"
OUT_OF_SCOPE_REPLY = (
    "Puedo ayudarte únicamente con los servicios y citas de BARBER CG 💈 "
    "¿Quieres ver precios o agendar?"
)
BUSINESS_TZ = ZoneInfo("America/Chihuahua")


def buffer_inbound(wa_id: str, message_id: str, text: str) -> None:
    """Job rápido: guarda el mensaje y reprograma el debounce. Lo dispara el webhook."""
    if already_processed(message_id):
        logger.info("mensaje duplicado ignorado wa_id_hash=%s", hash_wa_id(wa_id))
        return
    push_pending_message(wa_id, text)
    schedule_processing(wa_id)


def process_wa_id(wa_id: str) -> None:
    """Job que dispara el debounce: junta los mensajes pendientes y corre el agente."""
    try:
        if not check_rate_limit(wa_id):
            logger.warning("rate limit excedido wa_id_hash=%s", hash_wa_id(wa_id))
            return

        messages = pop_pending_messages(wa_id)
        if not messages:
            return

        prompt = "\n".join(messages)
        if is_agenda_link_request(prompt):
            send_text(wa_id, agenda_link_message(wa_id))
            return
        session = get_session()
        try:
            raw_history = load_history(session, wa_id)
            log_message(session, wa_id, "in", prompt)
            if not raw_history and is_greeting(prompt):
                reply = "¡Hola! Bienvenido a BARBER CG 💈"
                log_message(session, wa_id, "out", reply)
                send_welcome_buttons(wa_id)
                return
            if not is_business_message(prompt, has_business_context=bool(raw_history)):
                logger.info("mensaje fuera de alcance rechazado wa_id_hash=%s", hash_wa_id(wa_id))
                reply = OUT_OF_SCOPE_REPLY
            else:
                reply = _run_agent(session, wa_id, prompt)
            log_message(session, wa_id, "out", reply)
        finally:
            session.close()

        send_text(wa_id, reply)
    except Exception:
        # A broken DB/Redis job must not take the worker down permanently.
        logger.exception("fallo procesando mensaje wa_id_hash=%s", hash_wa_id(wa_id))
        send_text(wa_id, FALLBACK_REPLY)


def _run_agent(session: Session, wa_id: str, prompt: str) -> str:
    try:
        raw_history = load_history(session, wa_id)
        history = ModelMessagesTypeAdapter.validate_json(raw_history) if raw_history else []
        deps = BotDeps(wa_id=wa_id, db=session)
        current_local = datetime.now(BUSINESS_TZ)
        current_timestamp = current_local.strftime("%Y-%m-%d %H:%M")
        dated_prompt = (
            f"[Fecha y hora actual en Chihuahua: {current_timestamp}. "
            "Interpreta hoy, mañana y expresiones como 'dentro de dos horas' desde este momento. "
            "Para una cita redondea al siguiente bloque de 30 minutos y usa formato AAAA-MM-DD HH:MM.]\n"
            f"{prompt}"
        )
        result = asyncio.run(
            asyncio.wait_for(
                get_agent().run(dated_prompt, deps=deps, message_history=history),
                timeout=LLM_TIMEOUT_SECONDS,
            )
        )
        save_history(session, wa_id, result.all_messages_json())
        return sanitize_reply(str(result.output))
    except TimeoutError:
        logger.warning("timeout del LLM wa_id_hash=%s", hash_wa_id(wa_id))
        return FALLBACK_REPLY
    except Exception:
        session.rollback()
        logger.exception("error corriendo el agente wa_id_hash=%s", hash_wa_id(wa_id))
        return FALLBACK_REPLY
