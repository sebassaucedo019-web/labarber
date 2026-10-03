# AGENTS.md

Instrucciones para el agente de código que abre este repo (Claude Code, Cursor, Codex, etc.). Si sos ese agente: seguí esto antes de escribir código nuevo.

## Tu rol acá

Alguien bajó este template para armar su propio bot de WhatsApp con IA. Tu trabajo es entrevistarlo con las preguntas de abajo y, con las respuestas, dejar el repo andando para su caso: completar `.env`, elegir qué carpetas de `examples/` copiar a `app/`, y ajustar `app/agent/tools.py` / `app/agent/agent.py` a su negocio real. No asumas nada que no te haya contestado.

Si es la primera vez que abre este repo y todavía no tiene ninguna cuenta creada (Meta, OpenAI, etc.), mostrale primero [MANUAL-DE-USUARIO.md](MANUAL-DE-USUARIO.md) — ahí está el orden de qué crear y qué va a necesitar de cada cuenta, antes de meterse con la entrevista de abajo.

## Paso 0 — Fijate si ya hay un brief del negocio

Mirá si existe `context/brief-empresa.md` (el archivo real, no la plantilla
`context/brief-empresa.md.example`).

- **Si existe**: leelo primero. Usalo para responder vos mismo las preguntas del Paso 1
  que ya cubre, y preguntale al usuario solo lo que falte o esté ambiguo — no le hagas
  repetir por chat lo que ya escribió ahí.
- **Si no existe**: ofrecele armarlo junto con la entrevista, como alternativa a
  contestar pregunta por pregunta. Si te pasa un párrafo suelto sobre el negocio (o el
  texto de su web), armá vos `context/brief-empresa.md` con esa info, copiando la
  estructura de `context/brief-empresa.md.example`.

Este archivo no es solo para la entrevista: el bot en producción lo carga en su system
prompt (`app/agent/agent.py`, `_build_system_prompt()`), así que completarlo es parte
del bot, no un paso previo descartable.

## Paso 1 — Entrevista

Preguntá esto en tandas chicas, no las doce preguntas juntas:

```yaml
proyecto:
  nombre:
  proposito:                       # una frase: qué resuelve el bot
  idioma_usuarios:                 # es / en / multi

alcance:
  casos_uso:                       # 3-5 máximo para v1
  fuera_de_alcance:                # explícito, evita scope creep
  volumen_estimado:                # conversaciones/mes

whatsapp:
  numero_nuevo:                    # confirmá: SIN cuenta de WhatsApp previa
  pais_usuarios:                   # afecta la tarifa por mensaje
  necesita_iniciar_conversacion:   # si sí -> plantillas, avisale que tardan en aprobarse

tecnico:
  modelo_openai:                   # ayudalo a elegir uno vigente, no asumas un nombre fijo
  herramientas:                    # funciones que el agente va a poder llamar
  sistemas_a_integrar:             # CRM, calendario, pedidos...
  necesita_audio:                  # sí/no -> examples/audio_transcripcion
  necesita_flows:                  # sí/no -> examples/flows_formulario
  escalado_humano:                 # canal (Slack/Discord/email vía n8n/Chatwoot) -> ESCALATION_WEBHOOK_URL
```

## Paso 2 — Con las respuestas

1. Completá `.env` a partir de `.env.example` con lo que ya sepas. Dejá en blanco lo que solo Meta puede darle (token, `phone_number_id`, `app_secret`) y decile exactamente dónde sacarlo — ver [docs/02-configuracion-meta.md](docs/02-configuracion-meta.md). Ese `.env` es el del número de prueba — explicale que el número de producción va en credenciales separadas (`.env.production`, nunca en su laptop) recién cuando llegue al deploy, ver [docs/07-entornos-test-vs-produccion.md](docs/07-entornos-test-vs-produccion.md).
2. Reescribí el `BASE_SYSTEM_PROMPT` de `app/agent/agent.py` con el propósito real del bot (o mejor, volcá eso en `context/brief-empresa.md` — se suma solo, ver Paso 0).
3. Reemplazá los tools de ejemplo en `app/agent/tools.py` (`buscar_pedido`, `agendar`) por los que el usuario realmente necesita. Dejá `escalar_humano` — todo bot lo necesita — y asegurate de que `ESCALATION_WEBHOOK_URL` quede configurada en su `.env` (ver [docs/08-escalado-a-humano.md](docs/08-escalado-a-humano.md)); el código ya está conectado, solo falta la variable.
4. Si pidió audio, CRM o Flows: copiá la carpeta correspondiente de `examples/` a `app/`, seguí las instrucciones de su propio `README.md`, y avisale qué variables de entorno nuevas tiene que completar.
5. Mostrale [docs/00-ruta-de-construccion.md](docs/00-ruta-de-construccion.md) y decile en qué etapa está parado y qué sigue.
6. Antes de hablar de producción: recordale correr `uv run pytest` y repasar [docs/06-checklist-pre-lanzamiento.md](docs/06-checklist-pre-lanzamiento.md). No te lo saltees vos tampoco.

## Lo que no tenés que hacer

- No inventes valores de Meta (`META_APP_SECRET`, tokens, `phone_number_id`) — solo existen después de que el usuario crea la app en developers.facebook.com.
- No digas que esto ya está listo para producción sin pasar por el checklist.
- No confundas **Meta Business Agent** (el producto de IA propio de Meta, separado y opcional) con el bot custom de este repo — ver [docs/03-pricing-y-costos.md](docs/03-pricing-y-costos.md) si el usuario pregunta por eso.
