from unittest.mock import MagicMock

import fakeredis
import pytest

from app.queue import debounce


class _FakeJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id


def test_schedule_processing_enqueues_a_job(
    monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.FakeStrictRedis
) -> None:
    fake_queue = MagicMock()
    fake_queue.enqueue_in.return_value = _FakeJob("job-1")
    fake_queue.connection = fake_redis
    monkeypatch.setattr(debounce, "get_queue", lambda: fake_queue)

    debounce.schedule_processing("5491100000000")

    fake_queue.enqueue_in.assert_called_once()
    assert fake_redis.get("debounce:5491100000000") == "job-1"


def test_schedule_processing_cancels_previous_job(
    monkeypatch: pytest.MonkeyPatch, fake_redis: fakeredis.FakeStrictRedis
) -> None:
    fake_redis.set("debounce:5491100000000", "old-job")
    fake_queue = MagicMock()
    fake_queue.enqueue_in.return_value = _FakeJob("job-2")
    fake_queue.connection = fake_redis
    monkeypatch.setattr(debounce, "get_queue", lambda: fake_queue)

    cancelled = {}

    class _FakeFetchedJob:
        def cancel(self) -> None:
            cancelled["called"] = True

    monkeypatch.setattr(debounce.Job, "fetch", lambda job_id, connection: _FakeFetchedJob())

    debounce.schedule_processing("5491100000000")

    assert cancelled.get("called") is True
    assert fake_redis.get("debounce:5491100000000") == "job-2"
