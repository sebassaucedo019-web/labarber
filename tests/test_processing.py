from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from app.agent.history import trim_history
from app.queue import tasks
from app.store.redis_store import claim_batch

WA_ID = "526143649949"
_real_run_agent = tasks._run_agent


@pytest.fixture
def worker(monkeypatch, fake_redis):
    session = Mock()
    monkeypatch.setattr(tasks, "get_session", lambda: session)
    monkeypatch.setattr(tasks, "log_message", Mock())
    monkeypatch.setattr(tasks.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(tasks, "send_text", Mock(return_value=True))
    monkeypatch.setattr(tasks, "send_welcome_buttons", Mock(return_value=True))
    monkeypatch.setattr(tasks, "_run_agent", Mock(return_value="Cita confirmada"))
    return fake_redis


def test_grouped_messages_are_processed_once(worker):
    worker.rpush(f"pending:{WA_ID}", "Quiero cita", "mañana", "5 pm")
    tasks.process_wa_id(WA_ID)
    tasks.process_wa_id(WA_ID)
    assert tasks._run_agent.call_count == 1
    assert tasks._run_agent.call_args.args[2] == "Quiero cita\nmañana\n5 pm"
    tasks.send_text.assert_called_once()


def test_failed_delivery_retries_reply_without_repeating_tools(worker):
    worker.rpush(f"pending:{WA_ID}", "Confirmo")
    tasks.send_text.side_effect = [False, True, True]
    with pytest.raises(RuntimeError, match="pendiente"):
        tasks.process_wa_id(WA_ID)
    assert worker.exists(f"batch:{WA_ID}")
    worker.rpush(f"pending:{WA_ID}", "Y los precios?")
    tasks.process_wa_id(WA_ID)
    assert tasks._run_agent.call_count == 1
    assert worker.lrange(f"pending:{WA_ID}", 0, -1) == ["Y los precios?"]
    tasks.process_wa_id(WA_ID)
    assert tasks._run_agent.call_count == 2


def test_menu_delivered_once_with_no_extra_text(worker):
    worker.rpush(f"pending:{WA_ID}", "Hola")
    tasks._run_agent.return_value = tasks.MENU_SENTINEL
    tasks.process_wa_id(WA_ID)
    tasks.send_welcome_buttons.assert_called_once_with(WA_ID)
    tasks.send_text.assert_not_called()


def test_interrupted_batch_does_not_repeat_unknown_mutations(worker):
    worker.rpush(f"batch:{WA_ID}", "Sí")
    worker.set(f"batch-started:{WA_ID}", "1")
    tasks.process_wa_id(WA_ID)
    tasks._run_agent.assert_not_called()
    tasks.send_text.assert_called_once_with(WA_ID, tasks.INTERRUPTED_REPLY)


def test_parallel_worker_cannot_consume_the_same_conversation(worker):
    worker.rpush(f"pending:{WA_ID}", "Sí")
    worker.set(f"processing:{WA_ID}", "another-worker", ex=180)
    with pytest.raises(RuntimeError, match="ya está"):
        tasks.process_wa_id(WA_ID)
    assert worker.lrange(f"pending:{WA_ID}", 0, -1) == ["Sí"]
    tasks._run_agent.assert_not_called()


def test_large_batches_never_discard_first_messages(fake_redis):
    fake_redis.rpush(f"pending:{WA_ID}", "a" * 4000, "b" * 4000, "c" * 4000)
    assert claim_batch(WA_ID, 8000) == ["a" * 4000]
    assert fake_redis.llen(f"pending:{WA_ID}") == 2
    assert claim_batch(WA_ID, 8000) == ["a" * 4000]


def test_history_trims_at_turn_boundary_and_removes_stale_system_prompt():
    history = [
        ModelRequest(parts=[SystemPromptPart("Fecha vieja"), UserPromptPart("Reserva")]),
        ModelResponse(parts=[ToolCallPart("agendar", {}, "call1")]),
        ModelRequest(parts=[ToolReturnPart("agendar", "ok", "call1")]),
        ModelResponse(parts=[TextPart("Agendada")]),
        ModelRequest(parts=[UserPromptPart("Mi cita")]),
        ModelResponse(parts=[TextPart("Mañana")]),
    ]
    trimmed = trim_history(history, 4)
    assert len(trimmed) == 2
    assert isinstance(trimmed[0].parts[0], UserPromptPart)
    assert all(
        not isinstance(p, SystemPromptPart) for msg in trim_history(history) for p in msg.parts
    )


@pytest.fixture
def agent_run(monkeypatch):
    session = Mock()
    monkeypatch.setattr(tasks, "load_history", lambda *args: b"")
    monkeypatch.setattr(tasks, "save_history", Mock())

    monkeypatch.setattr(tasks, "classify_message", AsyncMock(return_value="business"))

    async def run(prompt, **kwargs):
        return SimpleNamespace(
            output="Con gusto",
            all_messages=lambda: [
                ModelRequest(parts=[UserPromptPart(prompt)]),
                ModelResponse(parts=[TextPart("Con gusto")]),
            ],
        )

    agent = SimpleNamespace(run=run)
    monkeypatch.setattr(tasks, "get_agent", lambda: agent)
    return session, agent


def test_corrupt_history_does_not_silence_bot(agent_run, monkeypatch):
    session, agent = agent_run
    monkeypatch.setattr(tasks, "load_history", lambda *args: b"not valid JSON")
    tasks.classify_message.return_value = "greeting"
    assert tasks._run_agent(session, WA_ID, "Buenas") == tasks.MENU_SENTINEL
    tasks.classify_message.assert_awaited_once_with("Buenas", "")


@pytest.mark.parametrize(
    "text", ["Miguel", "pm", "Canselala", "Buenas malanas", "Puedo hablar con una persona"]
)
def test_natural_replies_have_contextual_routing(agent_run, text):
    session, agent = agent_run
    assert tasks._run_agent(session, WA_ID, text) == "Con gusto"
    tasks.classify_message.assert_awaited_once_with(text, "")


@pytest.mark.parametrize("text", ["Hola", "OLI", "Buenas malanas", "Que ondaaa", "buen dia"])
def test_greeting_is_decided_by_ai_not_spelling(agent_run, text):
    session, agent = agent_run
    tasks.classify_message.return_value = "greeting"
    agent.run = Mock(side_effect=AssertionError("Greeting must produce only the menu"))
    assert tasks._run_agent(session, WA_ID, text) == tasks.MENU_SENTINEL
    tasks.classify_message.assert_awaited_once_with(text, "")
    agent.run.assert_not_called()


def test_greeting_with_booking_keeps_business_intent(agent_run):
    session, agent = agent_run
    prompt = "Hola, quiero cancelar mi cita"
    assert tasks._run_agent(session, WA_ID, prompt) == "Con gusto"
    tasks.classify_message.assert_awaited_once_with(prompt, "")


def test_classifier_failure_answers_without_guessing_or_running_tools(agent_run):
    session, agent = agent_run
    tasks.classify_message.side_effect = TimeoutError()
    agent.run = Mock(side_effect=AssertionError("Must not guess intent on timeout"))
    assert tasks._run_agent(session, WA_ID, "Hola") == tasks.FALLBACK_REPLY
    tasks.classify_message.assert_awaited_once()
    agent.run.assert_not_called()


def test_staff_agenda_has_no_classifier_bypass(worker, agent_run, monkeypatch):
    from app.config import get_settings

    session, agent = agent_run
    monkeypatch.setenv("OWNER_WA_ID", WA_ID)
    get_settings.cache_clear()
    monkeypatch.setattr(tasks, "_run_agent", _real_run_agent)
    worker.rpush(f"pending:{WA_ID}", "dame mi agenda")
    tasks.process_wa_id(WA_ID)
    tasks.classify_message.assert_awaited_once_with("dame mi agenda", "")
    tasks.send_text.assert_called_once_with(WA_ID, "Con gusto")


def test_off_topic_intent_never_reaches_business_tools(agent_run, monkeypatch):
    session, agent = agent_run

    async def off_topic(*args):
        return "off_topic"

    monkeypatch.setattr(tasks, "classify_message", off_topic)
    agent.run = Mock(side_effect=AssertionError("Must not run business agent"))
    assert (
        tasks._run_agent(session, WA_ID, "En la barbería resuelve mi tarea")
        == tasks.OUT_OF_SCOPE_REPLY
    )
    agent.run.assert_not_called()


def test_committed_action_survives_model_failure(agent_run):
    session, agent = agent_run

    async def run(*args, deps, **kwargs):
        deps.completed_actions.append("Cita confirmada para Ana")
        raise TimeoutError()

    agent.run = run
    assert tasks._run_agent(session, WA_ID, "Sí confirmo") == "Cita confirmada para Ana"


def test_history_storage_failure_does_not_discard_answer(agent_run, monkeypatch):
    session, agent = agent_run
    monkeypatch.setattr(tasks, "save_history", Mock(side_effect=RuntimeError("db")))
    assert tasks._run_agent(session, WA_ID, "Quiero cita") == "Con gusto"


def test_history_failure_does_not_replace_greeting(agent_run, monkeypatch):
    session, agent = agent_run
    monkeypatch.setattr(tasks, "save_history", Mock(side_effect=RuntimeError("db")))
    tasks.classify_message.return_value = "greeting"
    assert tasks._run_agent(session, WA_ID, "Hola") == tasks.MENU_SENTINEL


def test_committed_result_overrides_incorrect_model_answer(agent_run):
    session, agent = agent_run

    async def run(prompt, *, deps, **kwargs):
        deps.completed_actions.append("Cita cancelada correctamente")
        return SimpleNamespace(
            output="No pude cancelar",
            all_messages=lambda: [
                ModelRequest(parts=[UserPromptPart(prompt)]),
                ModelResponse(parts=[TextPart("No pude cancelar")]),
            ],
        )

    agent.run = run
    assert tasks._run_agent(session, WA_ID, "Confirmo") == "Cita cancelada correctamente"
    saved = tasks.save_history.call_args.args[2]
    assert b"No pude cancelar" not in saved
    assert b"Cita cancelada correctamente" in saved


def test_pending_proposal_survives_model_timeout(agent_run):
    session, agent = agent_run

    async def run(*args, deps, **kwargs):
        deps.pending_action_reply = "Reservar para Ana. Confirma la cita."
        raise TimeoutError()

    agent.run = run
    assert tasks._run_agent(session, WA_ID, "Quiero cita") == "Reservar para Ana. Confirma la cita."


def test_empty_wakeup_does_not_delay_following_jobs(worker, monkeypatch):
    sleep = Mock()
    monkeypatch.setattr(tasks.time, "sleep", sleep)
    tasks.process_wa_id(WA_ID)
    sleep.assert_not_called()


def test_recovered_reply_schedules_remaining_messages(worker):
    worker.rpush(f"batch:{WA_ID}", "Mensaje anterior")
    worker.set(f"reply:{WA_ID}", "Respuesta ya preparada")
    worker.rpush(f"pending:{WA_ID}", "Y los precios?")
    tasks.process_wa_id(WA_ID)
    tasks._run_agent.assert_not_called()
    assert worker.llen("rq:queue:agente-whatsapp") == 1
    assert not worker.exists(f"batch:{WA_ID}", f"reply:{WA_ID}")
    tasks.process_wa_id(WA_ID)
    assert tasks._run_agent.call_args.args[2] == "Y los precios?"


def test_failed_follow_up_enqueue_preserves_batch_and_reply(worker, monkeypatch):
    worker.rpush(f"batch:{WA_ID}", "Anterior")
    worker.set(f"reply:{WA_ID}", "Respuesta anterior")
    worker.rpush(f"pending:{WA_ID}", "Siguiente")
    monkeypatch.setattr(tasks, "schedule_processing", Mock(side_effect=RuntimeError("queue")))
    with pytest.raises(RuntimeError, match="queue"):
        tasks.process_wa_id(WA_ID)
    assert worker.get(f"reply:{WA_ID}") == "Respuesta anterior"
    assert worker.lrange(f"batch:{WA_ID}", 0, -1) == ["Anterior"]
    assert worker.lrange(f"pending:{WA_ID}", 0, -1) == ["Siguiente"]


def test_audit_write_failure_does_not_silence_valid_message(worker, monkeypatch):
    worker.rpush(f"pending:{WA_ID}", "Mis servicios")
    monkeypatch.setattr(tasks, "log_message", Mock(side_effect=RuntimeError("audit unavailable")))
    tasks.process_wa_id(WA_ID)
    tasks.send_text.assert_called_once_with(WA_ID, "Cita confirmada")
    tasks._run_agent.assert_called_once()
    assert not worker.exists(f"batch:{WA_ID}")
    tasks.get_session().rollback.assert_called()


def test_expired_processing_lock_cannot_acknowledge_another_workers_batch(worker):
    worker.rpush(f"pending:{WA_ID}", "Mi cita")

    def deliver(*args):
        worker.set(f"processing:{WA_ID}", "replacement-worker", ex=180)
        return True

    tasks.send_text.side_effect = deliver
    with pytest.raises(RuntimeError, match="bloqueo"):
        tasks.process_wa_id(WA_ID)
    assert worker.exists(f"batch:{WA_ID}", f"reply:{WA_ID}")
    assert worker.get(f"processing:{WA_ID}") == "replacement-worker"


def test_expired_worker_cannot_overwrite_or_send_another_workers_reply(worker):
    worker.rpush(f"pending:{WA_ID}", "Mi cita")

    def run(*args):
        worker.set(f"processing:{WA_ID}", "replacement-worker", ex=180)
        worker.set(f"reply:{WA_ID}", "Respuesta del worker actual")
        return "Respuesta del worker anterior"

    tasks._run_agent.side_effect = run
    with pytest.raises(RuntimeError, match="bloqueo"):
        tasks.process_wa_id(WA_ID)
    assert worker.get(f"reply:{WA_ID}") == "Respuesta del worker actual"
    tasks.send_text.assert_not_called()


def test_expired_worker_does_not_start_agent_after_slow_audit(worker, monkeypatch):
    worker.rpush(f"pending:{WA_ID}", "Mi cita")

    def log(*args):
        worker.set(f"processing:{WA_ID}", "replacement-worker", ex=180)

    monkeypatch.setattr(tasks, "log_message", log)
    with pytest.raises(RuntimeError, match="bloqueo"):
        tasks.process_wa_id(WA_ID)
    tasks._run_agent.assert_not_called()
    tasks.send_text.assert_not_called()
    assert not worker.exists(f"batch-started:{WA_ID}")
