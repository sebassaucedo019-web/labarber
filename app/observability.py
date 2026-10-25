import hashlib
import logging
import time

from app.config import get_settings
from app.store.redis_store import get_redis


class RedactAccessQuery(logging.Filter):
    """Agenda bearer tokens and webhook verification tokens must not enter logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            args = list(record.args)
            if isinstance(args[2], str):
                args[2] = args[2].split("?", 1)[0]
                record.args = tuple(args)
        return True


def hash_wa_id(wa_id: str) -> str:
    """Para usar en logs — nunca loguees el número en claro (es dato personal)."""
    return hashlib.sha256(wa_id.encode()).hexdigest()[:16]


def check_rate_limit(wa_id: str) -> bool:
    settings = get_settings()
    r = get_redis()
    key = f"ratelimit:{hash_wa_id(wa_id)}:{int(time.time() // 60)}"
    pipe = r.pipeline()
    pipe.incr(key)
    pipe.expire(key, 60)
    count, _ = pipe.execute()
    return count <= settings.rate_limit_per_minute
