"""Emisor de eventos genérico hacia un CRM externo, vía webhook saliente configurable.

Patrón CRM-agnóstico: el bot no sabe nada de HubSpot, Pipedrive o Chatwoot. Emite eventos
JSON a CRM_WEBHOOK_URL y una capa intermedia (n8n, Zapier, Make) traduce al CRM real.
Ver README.md de esta carpeta para el detalle de esa capa intermedia y un ejemplo de uso
desde app/agent/tools.py.
"""

import logging
from datetime import UTC, datetime
from enum import StrEnum

import httpx
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)


class CRMEvent(StrEnum):
    """Eventos recomendados. Podés emitir cualquier string como event_type, pero usar
    estos nombres mantiene consistencia si después conectás varias integraciones."""

    LEAD_CREADO = "lead_creado"
    ESCALADO_A_HUMANO = "escalado_a_humano"
    PEDIDO_ACTUALIZADO = "pedido_actualizado"
    OPT_OUT = "opt_out"


class CRMEventPayload(BaseModel):
    event_type: str
    wa_id: str
    timestamp: datetime
    payload: dict


def emit_event(event_type: str, wa_id: str, payload: dict) -> None:
    """Manda un evento al CRM_WEBHOOK_URL configurado. Si no está seteada, no hace nada:
    el bot funciona igual sin CRM conectado, esto nunca debe romper el flujo principal.

    wa_id va en claro (no hasheado) a propósito: la capa intermedia (n8n, Zapier, etc.)
    lo necesita para crear o matchear el contacto en el CRM real. Si tu webhook receptor
    es solo para métricas internas y no necesitás el número, hasheálo vos del otro lado."""
    webhook_url = get_settings().crm_webhook_url
    if not webhook_url:
        return

    event = CRMEventPayload(
        event_type=event_type,
        wa_id=wa_id,
        timestamp=datetime.now(UTC),
        payload=payload,
    )
    _post_event(webhook_url, event)


def _post_event(webhook_url: str, event: CRMEventPayload) -> None:
    try:
        httpx.post(webhook_url, json=event.model_dump(mode="json"), timeout=5)
    except httpx.HTTPError:
        logger.exception("no se pudo emitir evento CRM event_type=%s", event.event_type)
