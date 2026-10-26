import logging

from rq import SimpleWorker

from app.config import get_settings
from app.notifications import outbox_dispatcher
from app.queue.client import get_queue
from app.queue.tasks import close_async_runner
from app.store.postgres import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    logger.info("worker listo openai_model=%s", settings.openai_model)
    init_db()
    queue = get_queue()
    # SimpleWorker avoids os.fork(), which is unavailable on Windows.
    try:
        with outbox_dispatcher():
            SimpleWorker([queue], connection=queue.connection).work(with_scheduler=True)
    finally:
        close_async_runner()


if __name__ == "__main__":
    main()
