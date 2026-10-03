from rq import Worker

from app.queue.client import get_queue
from app.store.postgres import init_db


def main() -> None:
    init_db()
    queue = get_queue()
    Worker([queue], connection=queue.connection).work(with_scheduler=True)


if __name__ == "__main__":
    main()
