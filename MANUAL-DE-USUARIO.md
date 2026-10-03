# Manual de usuario

📺 **Video de referencia de este template:** [mirá acá cómo se usa, paso a paso](https://www.youtube.com/watch?v=ANsWFx_yvfs&list=PLItELtCfBA389ShH6qJOUkjZdRsbTQg44&index=25).

Por dónde empezar: qué cuentas crear, en qué orden, y qué vas a necesitar de cada una. Si ya tenés todo esto claro, andá directo a [docs/00-ruta-de-construccion.md](docs/00-ruta-de-construccion.md) para el orden de construcción del código, o abrí el repo con un agente de código y decile que lea [AGENTS.md](AGENTS.md).

## 1. Herramientas en tu máquina

- [ ] Python 3.11+ y [uv](https://docs.astral.sh/uv/) instalados
- [ ] Docker (para levantar Redis/Postgres local con `docker-compose.yml`)
- [ ] Un editor con un agente de código (Claude Code, Cursor) — no es obligatorio, pero con `AGENTS.md` acorta mucho el arranque (ver [README](README.md))
- [ ] Si bajaste esto como `.zip` (no con `git clone`): corré `git init` en la carpeta antes de empezar — un `.zip` no trae historial de git, y lo vas a necesitar para versionar tus cambios y eventualmente deployar

## 2. Cuentas a crear

En este orden, porque cada una depende un poco de la anterior:

| # | Cuenta | Para qué | Cuesta | Dónde |
|---|---|---|---|---|
| 1 | Meta Business (Business Manager) | Dueña de tu app y de tu número de WhatsApp | Gratis | [business.facebook.com](https://business.facebook.com) |
| 2 | App en Meta for Developers | Te da el número de prueba + credenciales del webhook | Gratis | [developers.facebook.com/apps](https://developers.facebook.com/apps) |
| 3 | OpenAI | El modelo que corre el agente | Pago por uso (tokens) | [platform.openai.com](https://platform.openai.com) |
| 4 | Railway (para el deploy) | Donde vive el bot en producción | USD 20 gratis con [nuestro link de referido](https://railway.app?referralCode=ElklE4) (declarado: nos deja algo de comisión), USD 5 si te creás la cuenta sin él, después pago por uso | [railway.app](https://railway.app) |

Opcionales — solo si tu bot los necesita, no hace falta crearlas de entrada:

| # | Cuenta | Para qué | Cuándo hace falta |
|---|---|---|---|
| 5 | Groq | Transcripción de audio | Si tu bot recibe notas de voz — [integraciones/audio-voz.md](docs/integraciones/audio-voz.md) |
| 6 | Slack, Discord, n8n o Zapier | Escalado a humano | Siempre, antes de mostrarle el bot a alguien real — [08-escalado-a-humano.md](docs/08-escalado-a-humano.md) |
| 7 | Tu CRM (HubSpot, Pipedrive, etc.) | Sincronizar leads/pedidos | Solo si ya usás uno — [integraciones/crm.md](docs/integraciones/crm.md) |
| 8 | Dominio propio (+ Cloudflare, gratis) | Túnel de desarrollo permanente | Recomendado desde el día 1 — [scripts/dev_tunnel.md](scripts/dev_tunnel.md) |

## 3. Las variables que vas a ir reuniendo

Todo esto termina en tu `.env` (copiado de `.env.example`). No hace falta juntarlas todas antes de arrancar — las vas consiguiendo a medida que avanzás por la [ruta de construcción](docs/00-ruta-de-construccion.md):

| Variable | Sale de la cuenta # | ¿Obligatoria? |
|---|---|---|
| `META_APP_SECRET`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN` | 2 (token permanente vía System User, en 1) | Sí |
| `META_WEBHOOK_VERIFY_TOKEN` | la inventás vos | Sí |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | 3 | Sí |
| `REDIS_URL`, `DATABASE_URL` | Docker local en desarrollo; Railway (4) en producción | Sí |
| `ESCALATION_WEBHOOK_URL` | 6 | Sí, antes de mostrarle el bot a alguien real |
| `GROQ_API_KEY` | 5 | Solo si sumás audio |
| `CRM_WEBHOOK_URL` | 7 | Solo si sincronizás CRM |

De dónde sacar cada valor de Meta, con el detalle exacto: [docs/02-configuracion-meta.md](docs/02-configuracion-meta.md).

## 4. El camino recomendado, de punta a punta

1. Cuentas 1 y 2 (Meta) — sacás el número de prueba, gratis, sin tarjeta.
2. Cuenta 3 (OpenAI) — sacás tu API key.
3. Completás `context/brief-empresa.md` (copiado de `context/brief-empresa.md.example`) con la info de tu negocio.
4. Abrís el repo con un agente de código y le decís que lea `AGENTS.md` — te entrevista con lo que falte y arma el `.env` — o seguís [docs/00-ruta-de-construccion.md](docs/00-ruta-de-construccion.md) a mano.
5. Desarrollás local con el número de prueba + un túnel — [scripts/dev_tunnel.md](scripts/dev_tunnel.md).
6. Configurás el escalado a humano (cuenta 6) — no es opcional antes de que alguien real hable con el bot.
7. Cuando esté probado: cuenta 4 (Railway) para el deploy — [docs/04-despliegue.md](docs/04-despliegue.md).
8. Recién ahí: número de producción (por default, alta nueva en la cuenta 1 — si ya tenés un número de WhatsApp Business en uso que querés preservar, hay una alternativa llamada Coexistence, bastante más compleja: ver [docs/09-numero-nuevo-o-coexistencia.md](docs/09-numero-nuevo-o-coexistencia.md)) — [docs/07-entornos-test-vs-produccion.md](docs/07-entornos-test-vs-produccion.md).
9. Checklist final antes de mandar tráfico real: [docs/06-checklist-pre-lanzamiento.md](docs/06-checklist-pre-lanzamiento.md).

## Lo que no vas a encontrar acá

Este manual es el "qué juntar y en qué orden". El "por qué" de cada decisión de arquitectura está en [docs/01-arquitectura.md](docs/01-arquitectura.md), los errores más comunes en [docs/05-anti-patrones.md](docs/05-anti-patrones.md), y dudas puntuales en [docs/faq.md](docs/faq.md).
