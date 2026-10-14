import logging

from fastapi import FastAPI

from app.health import router as health_router
from app.agenda import router as agenda_router
from app.privacy import router as privacy_router
from app.webhook.router import router as webhook_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Agente WhatsApp (AIPaths)")
app.include_router(health_router)
app.include_router(agenda_router)
app.include_router(privacy_router)
app.include_router(webhook_router)
