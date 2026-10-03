# Integración con CRM

## Dos arquitecturas distintas — elegí antes de empezar

**Arquitectura A — el CRM es el dueño de la integración con Meta.** Herramientas como Wati, respond.io, Zoko, Twilio Flex, Trengo o Freshchat se conectan ellas directo a la Cloud API (son ellas las que reciben el webhook de Meta). Tu bot de IA custom no tiene mucho lugar acá — la mayoría de estas herramientas ya traen su propio motor de chatbot, que compite con lo que armamos en `app/agent/`. Tiene sentido si preferís pagar por una plataforma armada y no programar nada.

**Arquitectura B — tu bot es el dueño de la integración, el CRM es secundario (la que asume este template).** `app/webhook/router.py` sigue siendo el único que recibe los webhooks de Meta. El CRM/inbox solo recibe eventos que tu bot le empuja — para que un humano vea el historial o tome una conversación cuando el bot escala. Esto es lo que ya tenés armado: `ESCALATION_WEBHOOK_URL` ([08-escalado-a-humano.md](../08-escalado-a-humano.md)) y `examples/crm_webhook/`.

Si ya construiste (o estás construyendo) tu bot con este template, estás en la B — no tiene sentido migrar a una herramienta que te pide ceder el webhook.

## Arquitectura B: el patrón CRM-agnóstico de este template

Implementación de referencia: `examples/crm_webhook/`. Requiere `CRM_WEBHOOK_URL` en tu `.env`.

El bot emite eventos en JSON a un webhook saliente configurable, y una capa intermedia — n8n, Chatwoot o Zapier — traduce esos eventos al CRM específico que uses. Si mañana cambiás de HubSpot a Pipedrive, no tocás el bot: tocás la capa intermedia.

### Eventos recomendados

- **Nuevo lead**: se detectó un contacto nuevo o con intención de compra.
- **Escalado a humano**: la tool `escalar_humano` (`app/agent/tools.py`) se disparó — útil para que el CRM abra un caso o notifique a un agente.
- **Actualización de pedido**: el bot resolvió o modificó algo sobre un pedido existente.
- **Opt-out**: el usuario pidió `STOP`/`BAJA` — tiene que llegar al CRM para que no le vuelvan a escribir desde ningún canal, no solo desde el bot.

### CRMs más comunes en la audiencia

- **HubSpot**, **Pipedrive**, **Zoho**, **GoHighLevel**: los cuatro tienen webhooks entrantes nativos o vía Zapier/n8n, no hace falta SDK propio.
- **Chatwoot**: además de servir de inbox de escalado (ver [examples/escalado_chatwoot.md](../../examples/escalado_chatwoot.md)), funciona como CRM liviano si todavía no tenés uno — es la opción con más precedente de uso real para este patrón (Arquitectura B), gratis si la self-hosteás.
- **n8n + Chatwoot**: patrón muy usado en la práctica — n8n hace de orquestador/capa intermedia (recibe `CRM_WEBHOOK_URL` o `ESCALATION_WEBHOOK_URL`, decide qué hacer) y Chatwoot es el inbox final. Mismo modelo, con menos código propio.

## Arquitectura A: si preferís que una herramienta maneje todo

Esto implica que la herramienta se vuelve dueña del webhook de Meta en vez de tu bot — no es una integración liviana, es cambiar quién controla el canal. Precios de referencia (2025-2026, confirmá antes de decidir, cambian seguido):

| Herramienta | Desde | Nota |
|---|---|---|
| Wati | ~USD 279-349/mes (plan Business) + seats | Trae chatbot propio, sin plan gratis real |
| respond.io | USD 79-279/mes + cargo por contactos activos (termina en 400-700/mes en la práctica) | |
| Zoko | USD 49.99-59.99/mes + por conversación | Foco e-commerce/Shopify |
| Twilio Flex | USD 1/hora activa o ~150/mes/usuario | Pensado para call centers, sobredimensionado para un solopreneur |
| Trengo | desde €299-499/mes + bloques de conversación | Sin plan gratis |
| Freshchat | Free hasta 10 agentes (limitado), después USD 19-79/agente/mes | + ~20% markup de Freshworks sobre tarifas de Meta |

Todas mucho más caras que self-hostear Chatwoot (~USD 20/mes de VPS), y todas vienen con su propio chatbot que compite con `app/agent/`. Tienen sentido si el objetivo real es "no programar nada", no si ya invertiste en un bot custom.
