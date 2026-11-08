from __future__ import annotations

import asyncio
import logging
import time
from contextvars import copy_context
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from pydantic_ai.messages import (
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.usage import UsageLimits
from redis.exceptions import WatchError
from sqlalchemy.orm import Session

from app.agent.agent import get_agent
from app.agent.deps import BotDeps
from app.agent.history import conversational_context, trim_history
from app.agent.routing import classify_message
from app.agent.tools import MENU_SENTINEL
from app.config import get_settings
from app.identity import normalize_phone
from app.observability import check_rate_limit, hash_wa_id
from app.queue.control import decode_notice, encode_notice
from app.queue.debounce import schedule_processing
from app.safety import (
    OUT_OF_SCOPE_REPLY,
    STAFF_HELP_REPLY,
    STAFF_OUT_OF_SCOPE_REPLY,
    contains_banned_language,
    retire_agenda_links,
    sanitize_reply,
)
from app.sender import send_text, send_welcome_buttons, welcome_menu_text
from app.staff import scope as staff_scope
from app.store.postgres import get_session, load_history, log_message, save_history
from app.store.redis_store import claim_batch, decode, get_redis, release_lock

logger = logging.getLogger(__name__)

LLM_TIMEOUT_SECONDS = 25
MAX_BATCH_CHARS = 8000
MAX_HISTORY_MESSAGES = 24
FALLBACK_REPLY = "Tuve un problema al procesar tu mensaje. Intenta de nuevo en un momento."
INTERRUPTED_REPLY = (
    "Se interrumpió el proceso. Consulta tu cita para comprobar cómo quedó "
    "antes de volver a pedir un cambio."
)
BUSINESS_TZ = ZoneInfo("America/Chihuahua")
_runner: asyncio.Runner | None = None


def _run_async(awaitable):
    global _runner
    if _runner is None:
        _runner = asyncio.Runner()
    return _runner.run(awaitable, context=copy_context())


def close_async_runner() -> None:
    global _runner
    if _runner is not None:
        _runner.close()
        _runner = None


def buffer_inbound(wa_id: str, message_id: str, text: str, *, kind: str = "text") -> None:
    """Atomically accept input and queue work before acknowledging Meta."""
    wa_id = normalize_phone(wa_id)
    if wa_id is None or not message_id or (kind == "text" and not text.strip()):
        return
    if kind not in {"text", "media"}:
        raise ValueError("Unknown inbound kind")
    settings = get_settings()
    r = get_redis()
    dedupe = f"dedupe:{message_id}"
    pending = f"pending:{wa_id}"
    rate_key = f"ingress:{hash_wa_id(wa_id)}:{int(time.time() // 60)}"
    notice_key = rate_key + ":notified"
    while True:
        with r.pipeline() as pipe:
            try:
                pipe.watch(dedupe, pending, rate_key, notice_key)
                if pipe.exists(dedupe):
                    return
                count = int(pipe.get(rate_key) or 0)
                queued = pipe.llen(pending)
                limited = (
                    count >= settings.inbound_limit_per_minute
                    or queued >= settings.max_pending_messages - 1
                )
                notify_limit = (
                    limited
                    and not pipe.exists(notice_key)
                    and queued < settings.max_pending_messages
                )
                pipe.multi()
                pipe.set(dedupe, "1", ex=120 if limited else 7 * 24 * 60 * 60)
                if not limited:
                    pipe.incr(rate_key)
                    pipe.expire(rate_key, 120)
                    pipe.rpush(
                        pending, encode_notice(wa_id, "media") if kind == "media" else text[:4000]
                    )
                    schedule_processing(wa_id, pipeline=pipe)
                elif notify_limit:
                    pipe.set(notice_key, "1", ex=120)
                    pipe.rpush(pending, encode_notice(wa_id, "limit"))
                    schedule_processing(wa_id, pipeline=pipe)
                pipe.execute()
                return
            except WatchError:
                continue


def process_wa_id(wa_id: str) -> None:
    """Job que dispara el debounce: junta los mensajes pendientes y corre el agente."""
    r = get_redis()
    lock_key, token = f"processing:{wa_id}", uuid4().hex
    if not r.set(lock_key, token, nx=True, ex=180):
        raise RuntimeError("La conversación ya está siendo procesada")
    try:
        if not r.exists(f"pending:{wa_id}", f"batch:{wa_id}"):
            return
        time.sleep(max(0.0, get_settings().debounce_seconds))
        messages = claim_batch(wa_id, MAX_BATCH_CHARS)
        if not messages:
            return
        notices = list(
            dict.fromkeys(notice for value in messages if (notice := decode_notice(wa_id, value)))
        )
        text_messages = [value for value in messages if decode_notice(wa_id, value) is None]
        reply_key, started_key = f"reply:{wa_id}", f"batch-started:{wa_id}"
        reply = decode(r.get(reply_key))
        if reply is None:
            if r.exists(started_key):
                # A worker can die after a tool commits. Never repeat a mutation
                # blindly when its final response was not persisted.
                reply = INTERRUPTED_REPLY
            elif not text_messages:
                reply = "\n".join(notices)
            elif not check_rate_limit(wa_id):
                reply = "Recibí muchos mensajes seguidos. Espera un minuto y volvemos a intentarlo."
            else:
                prompt = "\n".join(text_messages)
                session = get_session()
                try:
                    _log_message_safely(session, wa_id, "in", prompt)
                    _set_batch_value(wa_id, token, started_key, "1")
                    reply = _run_agent(session, wa_id, prompt)
                finally:
                    session.close()
            if notices and text_messages:
                if reply == MENU_SENTINEL:
                    reply = welcome_menu_text(wa_id)
                reply += "\n" + "\n".join(notices)
        # A pre-upgrade reply can still be waiting in Redis. Preserve the batch
        # and its completed operations, but never resend a retired agenda link.
        reply = retire_agenda_links(reply)
        _set_batch_value(wa_id, token, reply_key, reply)
        delivered = (
            send_welcome_buttons(wa_id) if reply == MENU_SENTINEL else send_text(wa_id, reply)
        )
        if not delivered:
            raise RuntimeError("No se entregó la respuesta; queda pendiente para reintento")
        _complete_batch(wa_id, token)
        session = get_session()
        try:
            _log_message_safely(session, wa_id, "out", reply)
        finally:
            session.close()
    finally:
        release_lock(lock_key, token)


def _set_batch_value(wa_id: str, token: str, key: str, value: str) -> None:
    """An expired worker cannot overwrite the active worker's recovery state."""
    r = get_redis()
    lock_key = f"processing:{wa_id}"
    while True:
        with r.pipeline() as pipe:
            try:
                pipe.watch(lock_key)
                if decode(pipe.get(lock_key)) != token:
                    raise RuntimeError("El worker perdió el bloqueo de la conversación")
                pipe.multi()
                pipe.set(key, value)
                pipe.execute()
                return
            except WatchError:
                continue


def _complete_batch(wa_id: str, token: str) -> None:
    """Acknowledge delivery and schedule remaining input in one Redis transaction."""
    r = get_redis()
    lock_key, pending_key = f"processing:{wa_id}", f"pending:{wa_id}"
    while True:
        with r.pipeline() as pipe:
            try:
                pipe.watch(lock_key, pending_key)
                if decode(pipe.get(lock_key)) != token:
                    raise RuntimeError("El worker perdió el bloqueo de la conversación")
                has_pending = pipe.exists(pending_key)
                pipe.multi()
                pipe.delete(f"batch:{wa_id}", f"reply:{wa_id}", f"batch-started:{wa_id}")
                # Earlier wake-ups may have exhausted their retries delivering
                # the old batch. Remaining messages need a fresh wake-up.
                if has_pending:
                    schedule_processing(wa_id, pipeline=pipe)
                pipe.execute()
                return
            except WatchError:
                continue


def _log_message_safely(session: Session, wa_id: str, direction: str, content: str) -> None:
    try:
        log_message(session, wa_id, direction, content)
    except Exception:
        session.rollback()
        logger.exception(
            "falló auditoría de mensaje direction=%s wa_id_hash=%s", direction, hash_wa_id(wa_id)
        )


def _save_history_safely(session: Session, wa_id: str, history: list) -> None:
    try:
        save_history(session, wa_id, ModelMessagesTypeAdapter.dump_json(trim_history(history)))
    except Exception:
        session.rollback()
        logger.exception("no se guardó el historial wa_id_hash=%s", hash_wa_id(wa_id))


def _action_reply(deps: BotDeps) -> str | None:
    replies = list(deps.completed_actions)
    if deps.pending_action_reply:
        replies.append(deps.pending_action_reply)
    if deps.support_reply and (
        not replies
        or (
            deps.support_decision is not None
            and deps.support_decision.category in {"human_request", "manual_issue"}
        )
    ):
        replies.append(deps.support_reply)
    return sanitize_reply("\n".join(replies)) if replies else None


def _run_agent(session: Session, wa_id: str, prompt: str) -> str:
    deps = BotDeps(wa_id=wa_id, db=session, user_message=prompt)
    try:
        raw_history = load_history(session, wa_id)
        try:
            history = ModelMessagesTypeAdapter.validate_json(raw_history) if raw_history else []
        except ValueError:
            logger.warning("historial inválido wa_id_hash=%s", hash_wa_id(wa_id))
            history = []
        # Keep enough context for a natural conversation without allowing an old
        # thread to grow until every response becomes slow or hits model limits.
        history = trim_history(history, MAX_HISTORY_MESSAGES)
        history_text = conversational_context(history)
        deps.support_context = history_text
        direct_reply = None
        intent = _run_async(asyncio.wait_for(classify_message(prompt, history_text), timeout=12))
        is_staff = staff_scope(wa_id) is not None
        if intent == "off_topic":
            direct_reply = STAFF_OUT_OF_SCOPE_REPLY if is_staff else OUT_OF_SCOPE_REPLY
        elif intent == "greeting":
            direct_reply = MENU_SENTINEL
        elif intent == "unclear":
            direct_reply = (
                STAFF_HELP_REPLY
                if is_staff
                else ("¿Me aclaras qué necesitas de la barbería? Te ayudo con servicios y citas.")
            )
        if direct_reply:
            history.extend(
                [
                    ModelRequest(parts=[UserPromptPart(prompt)]),
                    ModelResponse(
                        parts=[
                            TextPart(
                                welcome_menu_text(wa_id)
                                if direct_reply == MENU_SENTINEL
                                else direct_reply
                            )
                        ]
                    ),
                ]
            )
            _save_history_safely(session, wa_id, history)
            return direct_reply
        current_local = datetime.now(BUSINESS_TZ)
        current_timestamp = current_local.strftime("%Y-%m-%d %H:%M")
        safety_note = (
            "[El mensaje contiene lenguaje ofensivo: no lo repitas ni lo conviertas en "
            "una conversación personal; redirige a la barbería si no hay una solicitud válida.]\n"
            if contains_banned_language(prompt)
            else ""
        )
        dated_prompt = (
            f"[Fecha y hora actual en Chihuahua: {current_timestamp}. "
            "Interpreta hoy, mañana y expresiones como 'dentro de dos horas' desde este momento. "
            "Para una cita redondea al siguiente bloque de 30 minutos "
            "y usa formato AAAA-MM-DD HH:MM.]\n"
            f"{safety_note}{prompt}"
        )
        result = _run_async(
            asyncio.wait_for(
                get_agent().run(
                    dated_prompt,
                    deps=deps,
                    message_history=history,
                    usage_limits=UsageLimits(request_limit=6, tool_calls_limit=8),
                ),
                timeout=LLM_TIMEOUT_SECONDS,
            )
        )
        reply = _action_reply(deps) or sanitize_reply(str(result.output))
        if (
            deps.menu_sent
            and not deps.completed_actions
            and not deps.pending_action_reply
            and not deps.support_reply
        ):
            reply = MENU_SENTINEL
        output_history = result.all_messages()
        if output_history and isinstance(output_history[-1], ModelResponse):
            for part in output_history[-1].parts:
                if isinstance(part, TextPart):
                    part.content = welcome_menu_text(wa_id) if reply == MENU_SENTINEL else reply
        _save_history_safely(session, wa_id, output_history)
        return reply
    except TimeoutError:
        session.rollback()
        logger.warning("timeout del LLM wa_id_hash=%s", hash_wa_id(wa_id))
        return _action_reply(deps) or FALLBACK_REPLY
    except Exception:
        session.rollback()
        logger.exception("error corriendo el agente wa_id_hash=%s", hash_wa_id(wa_id))
        return _action_reply(deps) or FALLBACK_REPLY
