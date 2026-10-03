import redis

from app.config import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def push_pending_message(wa_id: str, text: str) -> None:
    get_redis().rpush(f"pending:{wa_id}", text)


def pop_pending_messages(wa_id: str) -> list[str]:
    r = get_redis()
    key = f"pending:{wa_id}"
    pipe = r.pipeline()
    pipe.lrange(key, 0, -1)
    pipe.delete(key)
    messages, _ = pipe.execute()
    return messages
