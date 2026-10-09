from __future__ import annotations

from rq import Queue
from rq.job import Job

from app.config import get_settings
from app.queue.client import get_queue
from app.store.redis_store import get_redis


def schedule_processing(wa_id: str) -> None:
    """Reprograma el procesamiento del hilo cada vez que llega un mensaje nuevo,
    así juntamos varios mensajes cortos seguidos en una sola pasada del agente."""
    r = get_redis()
    queue = get_queue()

    previous_job_id = r.get(f"debounce:{wa_id}")
    if previous_job_id:
        if isinstance(previous_job_id, bytes):
            previous_job_id = previous_job_id.decode()
        _cancel(queue, str(previous_job_id))

    # SimpleWorker en Windows puede dejar jobs programados en espera.
    # En el demo encolamos inmediatamente para no perder respuestas.
    job = queue.enqueue("app.queue.tasks.process_wa_id", wa_id)
    r.set(f"debounce:{wa_id}", job.id, ex=30)


def _cancel(queue: Queue, job_id: str) -> None:
    try:
        Job.fetch(job_id, connection=queue.connection).cancel()
    except Exception:
        pass
