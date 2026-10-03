import fakeredis

from app.queue.dedupe import already_processed


def test_first_time_not_processed(fake_redis: fakeredis.FakeStrictRedis) -> None:
    assert already_processed("wamid.AAA") is False


def test_second_time_is_processed(fake_redis: fakeredis.FakeStrictRedis) -> None:
    already_processed("wamid.BBB")
    assert already_processed("wamid.BBB") is True


def test_different_ids_are_independent(fake_redis: fakeredis.FakeStrictRedis) -> None:
    already_processed("wamid.CCC")
    assert already_processed("wamid.DDD") is False
