import logging

from rq import SimpleWorker

from app.queue.client import get_queue
from app.store.postgres import init_db

logging.basicConfig(level=logging.INFO)


def main() -> None:
    init_db()
    queue = get_queue()
    # SimpleWorker avoids os.fork(), which is unavailable on Windows.
    SimpleWorker([queue], connection=queue.connection).work(with_scheduler=True)


if __name__ == "__main__":
    main()
