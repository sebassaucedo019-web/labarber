# Despliegue

Restricciones que impone el webhook: HTTPS público, respuesta rápida (ver [01-arquitectura.md](01-arquitectura.md)) y **uptime constante**. Meta degrada la calidad de tu número si los webhooks fallan de forma sostenida, y esa degradación te limita el volumen de envío. Esto descarta cualquier free tier que "duerme": el de Render apaga el servicio tras 15 minutos de inactividad y la primera petición después tarda cerca de un minuto; Fly.io ya no da crédito gratuito a cuentas nuevas.

Este repo ya trae `Dockerfile` (imagen con `uv`, corre `uvicorn app.main:app`) y `docker-compose.yml` (servicios `app`, `worker`, `redis`, `postgres`) en la raíz — cualquiera de las opciones de abajo parte de ahí.

| Opción | Cuándo |
|---|---|
| **Railway** | Arranque rápido. Deploy desde Git, Redis y Postgres integrados, `app` + `worker` en un mismo proyecto. Suele salir en $10–15/mes para carga de un solo desarrollador. |
| **VPS Hetzner + Coolify** | Costo mínimo y control total. CX22 (2 vCPU, 4 GB) ~$4/mes con 20 TB de tráfico. Datacenter europeo = buena latencia a Meta. Coolify tiene hoy más tracción y comunidad que Dokploy — es la opción a usar si dudás entre las dos. |
| **Google Cloud Run** | Si ya estás en GCP. `min-instances=1` obligatorio — con 0 el cold start rompe el mismo problema que un free tier que duerme. |
| **Servidor en casa + Cloudflare Tunnel** | Viable de verdad: túnel permanente, sin IP estática ni puertos abiertos (misma herramienta que en desarrollo, ver [scripts/dev_tunnel.md](../scripts/dev_tunnel.md)). El riesgo es tu luz y tu fibra. |

Recomendación: empezar en Railway, migrar a VPS cuando la factura pase de $40–50/mes.

## Deploy en Railway desde el CLI

Railway tiene CLI oficial y se puede hacer casi todo el deploy desde la terminal. Un
matiz importante: **Railway no lee `docker-compose.yml` directo por CLI** (sí existe esa
función arrastrando el archivo al dashboard, pero acá vamos por terminal) — hay que crear
los 4 servicios (`app`, `worker`, `postgres`, `redis`) uno por uno. Los comandos exactos
pueden variar con el tiempo — esto es un resumen del flujo, la fuente de verdad es
[docs.railway.com/cli](https://docs.railway.com/cli).

```bash
# Instalar y loguearte
npm i -g @railway/cli   # o: brew install railway
railway login

# Crear el proyecto (desde la raíz de este repo) y las bases de datos administradas
railway init
railway add --database postgres
railway add --database redis

# Crear y deployar el servicio "app"
railway add --service app
railway service app
railway up

# Crear y deployar el servicio "worker" (mismo Dockerfile, arranca distinto)
railway add --service worker
railway service worker
railway up
```

`app` y `worker` comparten el mismo `Dockerfile` que usás local con Docker Compose, pero
necesitan un comando de arranque distinto (`uvicorn app.main:app ...` vs.
`python -m app.queue.worker`). Railway no tiene un flag de CLI para esto — es el único
paso que se hace una vez por servicio desde el dashboard: **Settings → Deploy → Custom
Start Command**.

Variables de entorno — repetí para cada valor de `.env.example` (ver
[02-configuracion-meta.md](02-configuracion-meta.md) y
[08-escalado-a-humano.md](08-escalado-a-humano.md) para saber de dónde sale cada uno):

```bash
railway variable set OPENAI_API_KEY=sk-... -s app
railway variable set OPENAI_API_KEY=sk-... -s worker
```

`DATABASE_URL` y `REDIS_URL` no los escribís a mano: los referenciás directo desde los
servicios administrados que Railway ya creó:

```bash
railway variable set DATABASE_URL='${{Postgres.DATABASE_URL}}' -s app
railway variable set DATABASE_URL='${{Postgres.DATABASE_URL}}' -s worker
railway variable set REDIS_URL='${{Redis.REDIS_URL}}' -s app
railway variable set REDIS_URL='${{Redis.REDIS_URL}}' -s worker
```

Dominio público para el webhook (gratis, tipo `*.up.railway.app`) — esta es la URL que
después registrás en Meta como `callback_url`, ver
[07-entornos-test-vs-produccion.md](07-entornos-test-vs-produccion.md) (acá ya estamos
hablando del número de producción, con dominio fijo, no del túnel de desarrollo):

```bash
railway domain -s app
railway logs -s app       # para ver que arrancó bien
railway logs -s worker
```

### Probar sin pagar

Una cuenta nueva de Railway arranca con **USD 5** de crédito de prueba (sin tarjeta, 30
días). Si te la creás con un link de referido, ese crédito sube a **USD 20** — suficiente
para tener este bot corriendo un buen rato sin pagar nada. Link de referido de Gonza /
AIPaths (te da los USD 20, y a nosotros nos suma un poco de comisión — por transparencia
te lo decimos): **https://railway.app?referralCode=ElklE4**. Si ya tenés cuenta de
Railway, no hace falta que lo uses.

## En producción

- El deploy tiene que levantar `app` **y** `worker` — si solo corre `app`, los mensajes se encolan pero nadie los procesa.
- Dominio permanente apuntando a tu `callback_url`, nunca una URL de túnel temporal: un webhook que cambia en cada reinicio es exactamente lo que Meta penaliza.
- Ver [06-checklist-pre-lanzamiento.md](06-checklist-pre-lanzamiento.md) antes de mandar tráfico real.
