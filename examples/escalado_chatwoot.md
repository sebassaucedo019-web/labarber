# Escalado a humano vía Chatwoot

Guía de integración, no código productivo completo. Ninguno de los dos enfoques está
100% probado de punta a punta acá — son el punto de partida razonable, verificá contra
la documentación de Chatwoot (self-hosted, versión que estés corriendo) antes de meterlo
en producción.

Chatwoot es un helpdesk open-source (self-hosted o cloud) con inbox unificado. La idea:
cuando el bot no puede resolver algo (`escalar_humano` en `app/agent/tools.py`), un humano
tiene que verlo en algún lado y poder responder. Chatwoot es una opción típica para eso —
ver también [docs/integraciones/crm.md](../docs/integraciones/crm.md) para cómo se compara
con alternativas SaaS "todo en uno" (Wati, respond.io, etc.).

**Costo real de self-hostearlo**: la licencia es gratis (MIT), pagás solo la
infraestructura. Para producción estable hacen falta ~4GB RAM / 2 CPU — un VPS tipo
Hetzner/DigitalOcean de esa capacidad ronda **USD 20-24/mes** (el tier de $5-6 se queda
corto). Si preferís no hostear nada, Chatwoot Cloud tiene un plan gratis (2 agentes, 500
conversaciones/mes), pero ojo: **el canal nativo de WhatsApp Cloud API en la nube está
bloqueado detrás del plan Business (~USD 39/agente/mes)** — para el Enfoque B de abajo
(que no usa ese canal nativo) el plan gratis de Chatwoot Cloud alcanza.

## Enfoque A — Chatwoot como canal nativo de WhatsApp Cloud API

Chatwoot tiene su propia integración directa con WhatsApp Cloud API: le das el
`phone_number_id`, el token y el `app_secret`, y Chatwoot se suscribe al webhook de Meta
él mismo.

Problema: Meta permite **un solo webhook callback URL por app**. Si Chatwoot recibe el
webhook directo, tu `app/webhook/router.py` deja de recibir mensajes — Chatwoot pasa a ser
la puerta de entrada, no tu bot.

Para que tu agente de IA siga respondiendo automáticamente en este escenario, tenés que
conectarlo como **Agent Bot** de Chatwoot (Chatwoot expone una API para que un bot externo
reciba los mensajes entrantes de una conversación y responda). Es un cambio de arquitectura
más grande: reemplaza el rol de `app/webhook/router.py` + `app/queue/` por el ciclo de vida
de eventos de Chatwoot. No es "copiar un archivo de `examples/`", es repensar el punto de
entrada. Solo tiene sentido si de entrada tu equipo humano va a vivir en Chatwoot y el bot
es un asistente más dentro de esa herramienta.

## Enfoque B — Bot dueño del canal, Chatwoot solo para el handoff (recomendado para este template)

**Camino más simple, sin escribir código nuevo**: `escalar_humano` ya dispara
`ESCALATION_WEBHOOK_URL` (ver [docs/08-escalado-a-humano.md](../docs/08-escalado-a-humano.md))
— apuntala a un flujo de n8n o Zapier que reciba el evento y llame a la API de Chatwoot
para crear la conversación. Mismo resultado que el código de abajo, sin tocar `app/`.

El boceto en Python de acá sirve si preferís no depender de una capa intermedia: en vez
de (o además de) que `escalar_humano` dispare el webhook genérico, el bot llama directo
a la API de Chatwoot para crear/encontrar la conversación y empujarle el contexto — así
el equipo humano la ve aparecer en su inbox y puede tomarla.

Boceto conceptual (nombres de endpoint y payloads a confirmar contra la API real de tu
instancia — la Application API de Chatwoot vive bajo `/api/v1/accounts/{account_id}/...`
y se autentica con un header `api_access_token`):

```python
import httpx

CHATWOOT_BASE_URL = "https://tu-chatwoot.tudominio.com"
CHATWOOT_ACCOUNT_ID = "1"
CHATWOOT_INBOX_ID = "1"
CHATWOOT_API_TOKEN = "..."  # token de agente/API, no lo hardcodees — va en tu .env


def crear_conversacion_chatwoot(wa_id: str, mensaje: str) -> None:
    headers = {"api_access_token": CHATWOOT_API_TOKEN}
    base = f"{CHATWOOT_BASE_URL}/api/v1/accounts/{CHATWOOT_ACCOUNT_ID}"

    contacto = httpx.post(
        f"{base}/contacts",
        headers=headers,
        json={"identifier": wa_id, "phone_number": f"+{wa_id}"},
        timeout=10,
    ).json()

    conversacion = httpx.post(
        f"{base}/conversations",
        headers=headers,
        json={
            "source_id": wa_id,
            "inbox_id": CHATWOOT_INBOX_ID,
            "contact_id": contacto["payload"]["contact"]["id"],
        },
        timeout=10,
    ).json()

    httpx.post(
        f"{base}/conversations/{conversacion['id']}/messages",
        headers=headers,
        json={"content": mensaje, "message_type": "incoming"},
        timeout=10,
    )
```

Esto asume que ya existe un inbox "API" (no WhatsApp) en Chatwoot para recibir estos
handoffs — no es el mismo inbox nativo de WhatsApp del Enfoque A. Con este enfoque, si el
humano responde desde Chatwoot, esa respuesta **no vuelve sola a WhatsApp** — necesitás
además un webhook de Chatwoot hacia tu bot (evento `message_created` con
`message_type: outgoing`) que llame a `app/sender.py` para mandarla por WhatsApp. Eso es
una pieza más para construir, no viene en este ejemplo.

**Alternativa más robusta que este boceto**: Chatwoot tiene una **Agent Bot API**
pensada exactamente para este patrón — registrás tu bot como un "agente" más dentro de
Chatwoot (no solo alguien que crea conversaciones desde afuera), lo que te da más control
sobre asignación y reasignación de conversaciones entre el bot y humanos. Si vas en serio
con este enfoque, es mejor punto de partida que el REST genérico de arriba — ver
[Chatwoot: Create an Agent Bot](https://developers.chatwoot.com/api-reference/agentbots/create-an-agent-bot).

## Variables de entorno que necesitarías

Ninguna existe hoy en `.env.example` — si armás el Enfoque B, agregá algo como:

```
CHATWOOT_BASE_URL=
CHATWOOT_ACCOUNT_ID=
CHATWOOT_INBOX_ID=
CHATWOOT_API_TOKEN=
```

## Alternativas más simples que Chatwoot

Si esto te suena a mucho armado para lo que necesitás, `escalar_humano` puede simplemente
mandar un mensaje a un canal de Slack/Discord o un email — mucho menos setup que levantar
Chatwoot self-hosted. Chatwoot vale la pena cuando ya tenés (o vas a tener) varios agentes
humanos atendiendo conversaciones a la vez.
