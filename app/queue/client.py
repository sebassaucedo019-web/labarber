from rq import Queue

from app.store.redis_store import get_redis

QUEUE_NAME = "agente-whatsapp"


def get_queue() -> Queue:
    return Queue(QUEUE_NAME, connection=get_redis())
