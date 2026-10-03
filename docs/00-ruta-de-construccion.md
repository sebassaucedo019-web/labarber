# La ruta de construcción, de a poco

¿Todavía no tenés las cuentas de Meta/OpenAI/Railway creadas? Empezá por el [Manual de usuario](../MANUAL-DE-USUARIO.md) — esto de acá es el orden de construcción del código, no el de las cuentas.

No armes todo el día uno. Este repo ya trae la arquitectura de producción completa en `app/` (el brief es explícito: la separación receptor/cola/worker no es opcional — ver [01-arquitectura.md](01-arquitectura.md)), así que acá no hay una versión "de juguete" separada del código real. Lo que sigue es el orden en el que conviene *probar* y *extender* las piezas para no debuggear diez cosas a la vez.

## v0 — Contale al bot quién sos

Antes de tocar código: copiá `context/brief-empresa.md.example` a `context/brief-empresa.md` y completalo (nombre, tono, FAQs, políticas, qué se deriva a humano) — o pegale a tu agente de código cualquier info suelta que ya tengas del negocio y que te arme el archivo. Alimenta dos cosas: la entrevista de [AGENTS.md](../AGENTS.md) (no vas a repetir por chat lo que ya escribiste ahí) y el system prompt del bot en producción, que `app/agent/agent.py` carga solo si el archivo existe.

## v1 — Confirmar que Meta te habla

Antes de preocuparte por si el agente responde bien, confirmá que el mensaje llega. Son fallas distintas y mezclarlas hace perder horas.

1. Levantá el túnel ([scripts/dev_tunnel.md](../scripts/dev_tunnel.md)) y registrá el webhook con tu número de prueba ([02-configuracion-meta.md](02-configuracion-meta.md)) — nunca con el de producción, ver [07-entornos-test-vs-produccion.md](07-entornos-test-vs-produccion.md).
2. Arrancá solo lo mínimo: `docker compose up --no-deps app redis` (el `--no-deps` evita que Compose levante Postgres automáticamente por el `depends_on` de `app`). El `GET` de verificación y la validación de firma no necesitan ni el agente ni la base.
3. Mandate un mensaje real desde WhatsApp. Confirmá en los logs que `POST /webhook` devuelve 200 y que el mensaje quedó encolado.
4. Sumá el worker (`docker compose up worker`, que trae Postgres consigo) para que el agente efectivamente te conteste, usando las tools de ejemplo ya cableadas.

Qué archivo hace qué: `app/webhook/router.py` (verificación GET y recepción POST), `app/webhook/signature.py` (firma), `app/webhook/normalize.py` (parseo del payload), `app/agent/agent.py` (el agente), `app/agent/tools.py` (`buscar_pedido`, `agendar`, `escalar_humano`).

## v2 — Arquitectura de producción (ya está armada)

Si llegaste hasta acá, ya estás corriendo la v2: cola y worker con RQ + Redis, Postgres para historial y auditoría, y todos los guardrails de la tabla de [01-arquitectura.md](01-arquitectura.md) (idempotencia, debounce, timeout + fallback, rate limit, logs hasheados). No hay nada que "agregar" en esta etapa — es lo que ya corre en `app/`. Esta etapa es sobre entenderla antes de tocarla:

- Cola, dedupe, debounce: `app/queue/client.py`, `app/queue/dedupe.py`, `app/queue/debounce.py`, `app/queue/tasks.py`.
- Historial y auditoría: `app/store/postgres.py`, `app/store/models.py`, `app/store/redis_store.py`.
- Observabilidad: `app/observability.py`, `app/health.py`.

## v3 — WhatsApp Flows para formularios

Cuando necesites capturar datos estructurados (reserva, alta, dirección de envío), no se lo preguntes al LLM campo por campo — es peor UX y sale más caro (cada Flow es un mensaje facturable en vez de ocho idas y vueltas). Copiá `examples/flows_formulario/` a `app/` cuando lo necesites y conectalo como una tool más del agente.

## v4 — Escalado a humano

La tool `escalar_humano` en `app/agent/tools.py` ya existe desde la v1 y ya dispara un webhook real (`app/escalation.py`) — no es opcional, ver [05-anti-patrones.md](05-anti-patrones.md). Acá es donde configurás `ESCALATION_WEBHOOK_URL` para que apunte a un canal real (Slack, Discord, email vía n8n/Zapier) — checklist completo en [08-escalado-a-humano.md](08-escalado-a-humano.md). Si querés algo más completo que una notificación, como un inbox compartido, la opción es Chatwoot (`examples/escalado_chatwoot.md`).

## v5 — Audio (opcional)

Si tu negocio recibe notas de voz, sumá transcripción. Ver [integraciones/audio-voz.md](integraciones/audio-voz.md) y `examples/audio_transcripcion/`. Por default reusa `OPENAI_API_KEY` — no requiere cuenta ni extra nuevo, salvo que cambies a la alternativa Groq (más barata a volumen alto).

## v6 — Integración CRM (opcional)

Si necesitás que el bot avise a un CRM (lead nuevo, pedido actualizado, opt-out), no lo atés a un SDK puntual. Ver [integraciones/crm.md](integraciones/crm.md) y `examples/crm_webhook/`. Requiere `CRM_WEBHOOK_URL` en tu `.env`.

## v7 — Producción real

Deploy con uptime real (nada de free tier que duerme) y el checklist completo antes de mandar tráfico de verdad. Ver [04-despliegue.md](04-despliegue.md) y [06-checklist-pre-lanzamiento.md](06-checklist-pre-lanzamiento.md).
