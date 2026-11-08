# Preparación del despliegue de Red Level Barber

Estado al 8 de noviembre de 2026: archivos de preparación locales; **no se ha
desplegado Red Level Barber ni conectado Google Calendar**. Solo está confirmado
el nombre del nuevo negocio. No registrar todavía el webhook de sus clientes.

## Versiones verificadas

- GitHub `main`, comprobado en la página del repositorio:
  [`844bbcb9e2174932987523e13d9f9147d0c10f73`](https://github.com/sebassaucedo019-web/labarber/commit/844bbcb9e2174932987523e13d9f9147d0c10f73).
  Conserva BARBER CG, `app/agenda.py`, `app/panel.py` y sus plantillas.
- HEAD local: `b7c57cf885eadf0dc9f74ad66eee5d6256ba3f8b`, dos commits por delante
  de esa versión remota. Retira la agenda web.
- La adaptación a Red Level y otras correcciones están sin commit. Ninguno de
  los hashes anteriores incluye todos esos cambios ni estos archivos.
- No hay un commit desplegado ni un dominio de Red Level verificados.

Antes de publicar en `main`, comprobar si el proyecto anterior tiene autodeploys
desde esa rama. Un proyecto nuevo no impide que un push despliegue también el
anterior. No cambiar ese servicio: coordinar su independencia antes del push.
No hacer `git add .` sin revisar todos los cambios pendientes y los secretos.

## Infraestructura independiente

Crear el proyecto `Red Level Barber`, con ambiente `production`, sin clonar
servicios, volúmenes, variables o datos del proyecto anterior. Crear PostgreSQL
y Redis nuevos, con sus volúmenes persistentes, preferentemente en la misma región.
Usar red privada para las conexiones; no hacen falta dominios ni proxies públicos
para las bases. Configurar respaldos y comprobar el procedimiento de restauración.

Los JSON de esta carpeta configuran servicios existentes; **no crean** el proyecto,
las bases, los volúmenes, las variables ni los dominios. Se seleccionan explícitamente
en Railway, por eso no se agregó un `railway.json` en la raíz del repositorio.

| Ajuste | red-level-web | red-level-worker |
| --- | --- | --- |
| Repositorio | `sebassaucedo019-web/labarber`, `main` | El mismo |
| Commit | Una versión revisada de Red Level | Exactamente la misma versión |
| Root Directory | Raíz del repositorio | Raíz del repositorio |
| Config File | `/deploy/red-level/railway.web.json` | `/deploy/red-level/railway.worker.json` |
| Build | `DOCKERFILE`, `Dockerfile` | `DOCKERFILE`, `Dockerfile` |
| Arranque | CMD del Dockerfile; quitar cualquier override del dashboard | `python -m app.queue.worker` |
| Healthcheck | `/health`, timeout 120 s | Ninguno HTTP |
| Réplicas / suspensión | 1 / desactivada | 1 / desactivada |
| Red pública | Un dominio HTTPS, puerto efectivo de Uvicorn | Ninguna |

El Dockerfile ejecuta Uvicorn mediante `sh -c`, escuchando `0.0.0.0` y el `PORT`
que aporta Railway. No fijar otro puerto ni pasar `$PORT` literalmente al ejecutable.
Verificar el puerto en logs y en el destino del dominio.

Puede prepararse primero PostgreSQL/Redis y dejar web/worker sin desplegar hasta
contar con la versión y las variables correctas. No iniciar un contenedor con
secretos vacíos para hacerlo aparecer como configurado.

## Variables verificadas contra app/config.py local

Copiar `variables.example` en ambos servicios nuevos. Las referencias requieren
que las bases nuevas se llamen `Postgres` y `Redis`; si se renombran, ajustar los
nombres de las referencias. La versión local normaliza `postgresql://` y
`postgres://` a `postgresql+psycopg://`, compatible con `psycopg[binary]`.

Ingresar directamente en Railway Variables, con valores propios de Red Level:

| Variable | Uso / estado |
| --- | --- |
| `META_APP_SECRET` | Firma de los webhooks de la aplicación Meta correspondiente. Pendiente. |
| `META_WEBHOOK_VERIFY_TOKEN` | Valor privado elegido para verificar el webhook; idéntico en Meta y Railway. Pendiente. |
| `WHATSAPP_PHONE_NUMBER_ID` | Identificador del número de WhatsApp del nuevo bot. Pendiente. |
| `WHATSAPP_ACCESS_TOKEN` | Credencial con permisos para ese número. Pendiente. |
| `OPENAI_API_KEY` | Credencial del nuevo despliegue, ingresada como secreto. Pendiente. |
| `OPENAI_MODEL` | Conservar la elección del usuario: `gpt-6-luna`; acceso real pendiente de verificar. No sustituir silenciosamente. |
| `OWNER_WA_ID` | Número confirmado del nuevo dueño; no copiar el de BARBER CG. Pendiente. |
| `BARBERS` | JSON con nombres, teléfonos y turnos confirmados de Red Level. Pendiente. |

`BARBERS` sí está soportada. **Omitirla o usar `[]` activa Obed/Jesús/Yadier**;
no representa un negocio sin equipo. Cada entrada usa `name`, `phone` y `hours`.
`hours` mapea días `0` (lunes) a `6` (domingo) a intervalos de minutos desde
medianoche, en múltiplos de 30. Los días omitidos están cerrados cuando hay
`hours`; omitir `hours` activa por defecto 09:00–20:00 todos los días. No inventar
nombres, teléfonos ni turnos para completar el JSON.

Mantener sin configurar los contactos `BARBER_OBED_WA_ID`, `BARBER_JESUS_WA_ID`
y `BARBER_YADIER_WA_ID`; usar un directorio `BARBERS` completo y confirmado.
No copiar `.env`, claves, contactos, URLs de escalado o webhooks CRM anteriores.
No imprimir las variables resueltas ni guardarlas en Git o en este documento.

`AUTOMATIC_NOTICES_ENABLED=false` mantiene apagados los recordatorios automáticos,
pero **no** impide las respuestas normales ni todos los avisos de citas. Por eso
se mantiene desconectado el webhook hasta terminar la adaptación.
`APPOINTMENT_TEMPLATE_NAME`, `SUPPORT_TEMPLATE_NAME`, `REMINDER_TEMPLATE_NAME`
y `TURN_TEMPLATE_NAME` requieren plantillas reales aprobadas para sus usos;
no rellenarlas con nombres inventados. No hace falta configurar Groq para este paso.

## Bloqueos de negocio antes de conectar WhatsApp

- Confirmar catálogo, precios y duración. `app/agent/tools.py` aún contiene los
  cuatro servicios y tarifas anteriores. `SERVICE_DURATIONS` solo ajusta duración
  de esos nombres: no cambia catálogo ni precios.
- Confirmar ciudad/zona horaria. `app/scheduling.py`, `app/agent/tools.py` y otras
  rutas todavía usan `America/Chihuahua`; una variable `TZ` del contenedor no
  sustituye esas constantes.
- Confirmar turnos, dueño/barberos, anticipación y reglas de cancelación/cambio.
  El código todavía conserva reglas anteriores, incluidas las tres horas.
- Completar ubicación, pagos y aviso de privacidad de Red Level en el brief.
- Retirar las referencias operativas heredadas; la nota de pendientes del prompt
  no desactiva las herramientas que todavía contienen esas reglas.

Para la nueva base vacía, dejar `CALENDAR_UTC_MIGRATION_ENABLED=false`:
el código local la inicializa directamente en UTC. No importar datos de BARBER CG
ni habilitar una migración de su base. Véase `docs/12-correcciones-auditoria.md`
si en otro trabajo se necesita migrar datos históricos.

## Google Calendar: integración pendiente

No se encontró cliente Google, configuración de credenciales/calendario, llamadas
a la API ni persistencia del identificador de evento en el código de aplicación.
`app/store/calendar_time.py` convierte horas a UTC; **no** conecta Google Calendar.
No se agregan variables Google que el programa no reconoce.

Implementación necesaria en el repositorio antes de declarar esta parte conectada:

1. Un calendario normal dedicado, propiedad del negocio; habilitar Calendar API
   en su proyecto de Google Cloud. No hacen falta páginas de reservas premium.
2. Autenticación con credenciales propias. Si se usa cuenta de servicio, compartir
   ese calendario con su correo y permiso de modificar eventos. Guardar la clave
   únicamente como secreto en Railway; nunca hacer público el calendario.
3. Configuración validada para el calendario, credenciales, zona horaria confirmada
   y colores por identificador estable de barbero. Definir nombres de variables
   al implementar y documentar cuáles consume el worker.
4. Mantener PostgreSQL como fuente de verdad. Registrar las operaciones de
   sincronización de forma durable junto con la transacción de la cita, y
   procesarlas con reintentos acotados y estados visibles de error.
5. Persistir calendario e ID de evento por cita; usar un ID estable compatible
   con Google para que un timeout/reintento no cree duplicados. Actualizar el
   mismo evento al reagendar, cambiar de barbero/servicio o cancelar.
6. Exportar nombre del barbero, cliente, servicio, inicio y fin con zona horaria;
   no incluir teléfonos u otros datos innecesarios ni enviar invitaciones a
   clientes automáticamente. Definir el tratamiento de eventos borrados a mano.
7. Probar creación, cambio, cancelación, cambio de barbero/color, reintento tras
   timeout, orden de operaciones y recuperación de fallos con datos sintéticos.
   Probar después un calendario de prueba propio, sin mensajes a clientes reales.

Primera etapa: bot → Google Calendar. Editar en Google no modificará reservas
ni bloqueará horarios en el bot hasta implementar expresamente esa dirección.
Un solo calendario compartido muestra todas sus citas a quienes tienen acceso;
los colores no crean permisos por barbero.

## Verificación de un despliegue futuro

Verificación realizada en esta preparación (8 de noviembre de 2026):

- JSON de ambos servicios parseado; comprobados Dockerfile compartido, arranque
  distinto, healthcheck exclusivo de web, una réplica y suspensión desactivada.
- Suite local: **377 pruebas aprobadas en 46.33 s**, con HTTP real y solicitudes
  al modelo bloqueados por las fixtures. Fue necesario permitir sockets locales
  para que `asyncio` funcionara en Windows. Python local: 3.14; Docker usa 3.11.
- Ruff (`F,E9,B,UP`) y `git diff --check` aprobados.
- Build Docker no ejecutado: el daemon de Docker Desktop no está disponible.
- Railway pidió iniciar sesión en el navegador integrado. No se crearon servicios,
  variables, bases, dominios ni despliegues desde esta preparación.
- No se hizo commit ni push; no se enviaron mensajes ni se crearon eventos Google.

- Ejecutar `python -m pytest -q` y revisar `docs/06-checklist-pre-lanzamiento.md`.
  Registrar las limitaciones; los tests con SQLite/fakeredis no prueban los
  servicios reales ni el acceso al modelo.
- Comprobar build Docker con Python 3.11 y arranque sin errores de configuración.
- Crear tablas en la base nueva mediante el arranque existente; no agregar
  comandos de borrado ni una migración histórica al pre-deploy.
- Confirmar SHA idéntico en web/worker, `GET /health` 200, `GET /ready` 200
  y worker escuchando `agente-whatsapp` sin errores de PostgreSQL/Redis.
- Mantener HMAC en `/webhook`: una petición sin firma debe rechazarse. El GET
  de verificación debe devolver el challenge con el verify token correcto.
  Evitar que el token de esa comprobación termine en capturas o logs compartidos.
- Con la adaptación y secretos terminados, usar el dominio real del servicio
  web y registrar `https://<dominio-real>/webhook` en la aplicación Meta correcta.
- Comprobar recepción, ejecución de cola y respuesta con destinatarios de prueba
  autorizados para Red Level. No reutilizar los números de prueba del negocio anterior.
- Verificar Calendar por separado. HTTP 200 en `/health` no demuestra sincronización
  de citas ni entrega de WhatsApp. Registrar pruebas y pendientes de forma separada.

## Referencias de configuración

- [Railway: archivos por servicio](https://docs.railway.com/config-as-code)
- [Railway: campos y precedencia](https://docs.railway.com/config-as-code/reference)
- [Railway: esquema JSON](https://railway.com/railway.schema.json)
- [Google: crear eventos e IDs para evitar duplicados](https://developers.google.com/workspace/calendar/api/guides/create-events)
