import hashlib
import time

from app.config import get_settings
from app.store.redis_store import get_redis


def hash_wa_id(wa_id: str) -> str:
    """Para usar en logs — nunca loguees el número en claro (es dato personal)."""
    return hashlib.sha256(wa_id.encode()).hexdigest()[:16]


def check_rate_limit(wa_id: str) -> bool:
    settings = get_settings()
    r = get_redis()
    key = f"ratelimit:{wa_id}:{int(time.time() // 60)}"
    count = r.incr(key)
    if count == 1:
        r.expire(key, 60)
    return count <= settings.rate_limit_per_minute
