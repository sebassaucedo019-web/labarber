import logging

from rq import SimpleWorker

from app.config import get_settings
from app.queue.client import get_queue
from app.store.postgres import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    settings = get_settings()
    logger.info("worker listo openai_model=%s", settings.openai_model)
    init_db()
    queue = get_queue()
    # SimpleWorker avoids os.fork(), which is unavailable on Windows.
    SimpleWorker([queue], connection=queue.connection).work(with_scheduler=True)


if __name__ == "__main__":
    main()
