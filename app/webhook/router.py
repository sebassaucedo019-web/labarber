import logging

from fastapi import APIRouter, Request, Response

from app.config import get_settings
from app.queue.client import get_queue
from app.queue.tasks import buffer_inbound
from app.webhook.normalize import extract_text_messages
from app.webhook.signature import is_valid_signature

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/webhook")
def verify(request: Request) -> Response:
    settings = get_settings()
    params = request.query_params
    if (
        params.get("hub.mode") == "subscribe"
        and params.get("hub.verify_token") == settings.meta_webhook_verify_token
    ):
        return Response(content=params.get("hub.challenge", ""), media_type="text/plain")
    return Response(status_code=403)


@router.post("/webhook")
async def receive(request: Request) -> Response:
    """Valida la firma y encola. No llama al LLM acá — ver docs/01-arquitectura.md
    sobre por qué la separación receptor/worker no es opcional."""
    settings = get_settings()
    raw_body = await request.body()
    signature = request.headers.get("x-hub-signature-256")

    if not is_valid_signature(raw_body, signature, settings.meta_app_secret):
        logger.warning("firma inválida en webhook entrante")
        return Response(status_code=401)

    payload = await request.json()
    queue = get_queue()
    for message in extract_text_messages(payload):
        queue.enqueue(buffer_inbound, message["wa_id"], message["message_id"], message["text"])

    return Response(status_code=200)
