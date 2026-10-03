from app.store.redis_store import get_redis

DEDUPE_TTL_SECONDS = 60 * 60 * 24  # Meta puede reintentar hasta 24h el mismo message_id


def already_processed(message_id: str) -> bool:
    was_new = get_redis().set(f"dedupe:{message_id}", "1", nx=True, ex=DEDUPE_TTL_SECONDS)
    return not was_new
