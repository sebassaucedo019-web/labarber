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
from app.panel import router as panel_router
from app.panel_auth import router as auth_router
from fastapi import Request
from starlette.responses import JSONResponse

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
app.include_router(panel_router)
app.include_router(auth_router)


@app.middleware("http")
async def panel_security(request: Request, call_next):
    private = request.url.path.startswith(("/panel", "/api/agenda"))
    if private and request.method in {"POST", "PUT", "PATCH"}:
        try:
            if int(request.headers.get("content-length", "0")) > 16384:
                return JSONResponse({"detail": "Solicitud demasiado grande"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "Solicitud inválida"}, status_code=400)
        chunks, length = [], 0
        async for chunk in request.stream():
            length += len(chunk)
            if length > 16384:
                return JSONResponse({"detail": "Solicitud demasiado grande"}, status_code=413)
            chunks.append(chunk)
        request._body = b"".join(chunks)
    response = await call_next(request)
    if private:
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
            }
        )
    return response


app.mount("/agenda-assets", StaticFiles(directory=ASSET_DIR), name="agenda-assets")
