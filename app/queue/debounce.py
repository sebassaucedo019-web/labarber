from rq import Retry

from app.observability import hash_wa_id
from app.queue.client import get_queue


def schedule_processing(wa_id: str, *, pipeline=None) -> None:
    """Queue a wake-up; the receiver buffers independently of the worker."""
    queue = get_queue()
    job = queue.create_job(
        "app.queue.tasks.process_wa_id",
        args=(wa_id,),
        timeout=120,
        retry=Retry(max=4, interval=[10, 30, 60, 120]),
        description=f"conversation:{hash_wa_id(wa_id)}",
    )
    queue.enqueue_job(job, pipeline=pipeline)
