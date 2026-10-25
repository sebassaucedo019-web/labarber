from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text

from app.config import get_settings
from app.store.postgres import get_session

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
def readiness():
    try:
        # RQ's blocking connection cannot be reused with a short read timeout.
        with Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        ) as redis:
            redis.ping()
        with get_session() as session:
            session.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "unavailable"}, status_code=503)
    return {"status": "ok"}
