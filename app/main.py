import logging

from fastapi import FastAPI

from app.health import router as health_router
from app.webhook.router import router as webhook_router

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Agente WhatsApp (AIPaths)")
app.include_router(health_router)
app.include_router(webhook_router)
