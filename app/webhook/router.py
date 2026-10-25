import logging

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.queue.tasks import buffer_inbound
from app.webhook.normalize import extract_text_messages
from app.webhook.signature import is_valid_signature

logger = logging.getLogger(__name__)
router = APIRouter()
MAX_WEBHOOK_BYTES = 1024 * 1024


@router.get("/webhook")
def verify(request: Request) -> Response:
    settings = get_settings()
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and bool(params.get("hub.challenge"))
        and params.get("hub.verify_token") == settings.meta_webhook_verify_token
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@router.post("/webhook")
async def receive(request: Request) -> Response:
    """Valida la firma y encola. No llama al LLM acá — ver docs/01-arquitectura.md
    sobre por qué la separación receptor/worker no es opcional."""
    settings = get_settings()
    chunks = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_WEBHOOK_BYTES:
            return Response(status_code=413)
        chunks.append(chunk)
    raw_body = b"".join(chunks)
    signature = request.headers.get("x-hub-signature-256")

    if not is_valid_signature(raw_body, signature, settings.meta_app_secret):
        logger.warning("firma inválida en webhook entrante")
        return Response(status_code=401)

    try:
        import json

        payload = json.loads(raw_body)
    except ValueError:
        logger.warning("payload JSON inválido en webhook")
        return Response(status_code=400)
    if not isinstance(payload, dict):
        return Response(status_code=400)
    for message in extract_text_messages(
        payload, phone_number_id=settings.whatsapp_phone_number_id
    ):
        await run_in_threadpool(
            buffer_inbound, message["wa_id"], message["message_id"], message["text"]
        )

    return Response(status_code=200)
