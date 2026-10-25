import redis
from redis.exceptions import WatchError

from app.config import get_settings

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        # RQ expects byte responses from Redis; decode app-level values below.
        _client = redis.from_url(
            get_settings().redis_url,
            decode_responses=False,
            socket_connect_timeout=5,
        )
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
    return [
        message.decode("utf-8") if isinstance(message, bytes) else message for message in messages
    ]


def decode(value: bytes | str | None) -> str | None:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def claim_batch(wa_id: str, max_chars: int) -> list[str]:
    """Keep the claimed input until its response has been delivered."""
    r = get_redis()
    pending, batch = f"pending:{wa_id}", f"batch:{wa_id}"
    while True:
        with r.pipeline() as pipe:
            try:
                pipe.watch(pending, batch)
                current = pipe.lrange(batch, 0, -1)
                if current:
                    return [decode(value) for value in current]
                values = pipe.lrange(pending, 0, 39)
                selected = []
                size = 0
                for value in values:
                    text = decode(value)
                    if selected and size + len(text) + 1 > max_chars:
                        break
                    selected.append(text)
                    size += len(text) + 1
                if not selected:
                    return []
                pipe.multi()
                pipe.rpush(batch, *selected)
                pipe.ltrim(pending, len(selected), -1)
                pipe.execute()
                return selected
            except WatchError:
                continue


def release_lock(key: str, token: str) -> None:
    r = get_redis()
    while True:
        with r.pipeline() as pipe:
            try:
                pipe.watch(key)
                if decode(pipe.get(key)) != token:
                    return
                pipe.multi()
                pipe.delete(key)
                pipe.execute()
                return
            except WatchError:
                continue
