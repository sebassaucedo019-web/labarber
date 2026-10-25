from unittest.mock import Mock

import fakeredis
import pytest
from rq import Queue

from app.queue import debounce, tasks
from app.store import redis_store


@pytest.fixture
def queue(monkeypatch):
    redis = fakeredis.FakeRedis(decode_responses=False)
    monkeypatch.setattr(redis_store, "_client", redis)
    return Queue("agente-whatsapp", connection=redis)


def test_buffers_once_and_enqueues_a_real_rq_job(queue):
    tasks.buffer_inbound("5216143649949", "wamid.1", "Hola")
    tasks.buffer_inbound("526143649949", "wamid.1", "Hola")
    assert queue.count == 1
    job = queue.jobs[0]
    assert job.func_name == "app.queue.tasks.process_wa_id"
    assert job.args == ("526143649949",)
    assert job.retries_left == 4
    assert queue.connection.lrange("pending:526143649949", 0, -1) == [b"Hola"]


def test_failed_enqueue_does_not_mark_message_processed(queue, monkeypatch):
    original = tasks.schedule_processing

    def fail(*args, **kwargs):
        raise ConnectionError("Redis unavailable")

    monkeypatch.setattr(tasks, "schedule_processing", fail)
    with pytest.raises(ConnectionError):
        tasks.buffer_inbound("5216143649949", "wamid.retry", "Agendar")
    assert not queue.connection.exists("dedupe:wamid.retry")
    assert not queue.connection.exists("pending:526143649949")
    monkeypatch.setattr(tasks, "schedule_processing", original)
    tasks.buffer_inbound("5216143649949", "wamid.retry", "Agendar")
    assert queue.count == 1


def test_later_input_does_not_cancel_running_job(queue):
    debounce.schedule_processing("526143649949")
    original = queue.jobs[0]
    tasks.buffer_inbound("5216143649949", "wamid.next", "5 pm")
    assert queue.count == 2
    assert original.get_status().value == "queued"


def test_recovery_follow_up_is_an_executable_rq_job(queue, monkeypatch):
    wa_id = "526143649949"
    redis = queue.connection
    redis.rpush(f"batch:{wa_id}", "Anterior")
    redis.set(f"reply:{wa_id}", "Respuesta recuperada")
    redis.rpush(f"pending:{wa_id}", "Quiero conocer los precios")
    monkeypatch.setattr(tasks, "get_session", Mock(return_value=Mock()))
    monkeypatch.setattr(tasks, "log_message", Mock())
    monkeypatch.setattr(tasks.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(tasks, "send_text", Mock(return_value=True))
    run = Mock(return_value="Corte normal: $120")
    monkeypatch.setattr(tasks, "_run_agent", run)
    tasks.process_wa_id(wa_id)
    assert queue.count == 1
    follow_up = queue.jobs[0]
    assert follow_up.func_name == "app.queue.tasks.process_wa_id"
    assert follow_up.args == (wa_id,)
    follow_up.perform()
    assert run.call_args.args[2] == "Quiero conocer los precios"
    tasks.send_text.assert_any_call(wa_id, "Corte normal: $120")
    assert not redis.exists(f"pending:{wa_id}", f"batch:{wa_id}", f"reply:{wa_id}")
