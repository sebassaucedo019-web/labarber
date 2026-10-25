import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from app.agenda import ASSET_DIR
from app.agenda import router as agenda_router
from app.health import router as health_router
from app.observability import RedactAccessQuery
from app.privacy import router as privacy_router
from app.store.postgres import init_db
from app.webhook.router import router as webhook_router

logging.basicConfig(level=logging.INFO)
logging.getLogger("uvicorn.access").addFilter(RedactAccessQuery())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await run_in_threadpool(init_db)
    yield


app = FastAPI(title="Agente WhatsApp (AIPaths)", lifespan=lifespan)
app.include_router(health_router)
app.include_router(agenda_router)
app.include_router(privacy_router)
app.include_router(webhook_router)
app.mount("/agenda-assets", StaticFiles(directory=ASSET_DIR), name="agenda-assets")
