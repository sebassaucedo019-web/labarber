# Bloc de correcciones — BARBER CG

Revisión local del 7 de noviembre de 2026. Estos cambios no equivalen a un
despliegue verificado ni a una garantía de ausencia de errores.

## Corregido en código

| Problema | Comportamiento corregido |
| --- | --- |
| Mover una cita próxima y luego cancelarla eludía las tres horas. | El cliente no puede mover una cita a menos de tres horas. El equipo debe realizar y confirmar el cambio desde un número verificado. La regla se vuelve a comprobar al confirmar. |
| El equipo no tenía una operación para autorizar esos cambios. | `reagendar_para_cliente`: un barbero modifica sus citas dentro de su propia agenda; el dueño también puede reasignar. Se identifica una cita, se confirma en otro turno y se registra el actor. Afirmar ser el dueño no concede permisos. |
| Disponibilidad consideraba solo el inicio y 30 minutos. | Duración configurable por servicio, persistida en cada reserva. Se comprueba el intervalo completo frente a citas, bloqueos y fin de turno, también al reagendar. Las citas anteriores conservan sus 30 minutos. |
| No había anticipación mínima/máxima configurable. | Se aplican los límites configurados tanto a disponibilidad como a reserva y cambio. Los valores reales del negocio aún deben confirmarse. |
| Fechas de agenda locales sin zona explícita en almacenamiento. | Persistencia UTC; las herramientas siguen mostrando hora civil de `America/Chihuahua`. Migración transaccional con marcador para no convertir dos veces; rechaza horas históricas ambiguas en vez de adivinarlas. |
| Entradas repetidas podían llenar la cola antes del filtro. | Límite de mensajes por número en la recepción, cola acotada por conversación y un aviso de límite por minuto. Se conserva la deduplicación de mensajes aceptados. |
| Costos de IA sin tope global de turnos. | Límite global configurable de turnos de IA por minuto, además del límite individual y los límites existentes de herramientas/peticiones. Esto no sustituye un límite monetario y alertas del proveedor. |
| Audios, imágenes, ubicaciones y archivos se ignoraban. | Respuesta explícita pidiendo texto. No se descargan ni se envían al modelo los adjuntos. Los avisos internos de la cola están autenticados para impedir que un texto del cliente los suplante. |
| Avisos al equipo/cliente fuera de 24 horas usaban texto libre. | Ventana por destinatario basada en la fecha del mensaje firmado de Meta. Reintentos antiguos no la prolongan. Fuera de ventana se requiere la plantilla aprobada correspondiente. Si falta, el aviso no se considera enviado. |
| Reintentar una plantilla tras un resultado de red incierto podía duplicarla. | El outbox conserva el estado `uncertain` para revisión; no vuelve a enviar automáticamente una plantilla cuya presentación quedó incierta. |
| No había mecanismo de depuración de chats antiguos. | Comando de retención para conversaciones y logs, con plazo explícito y simulación por defecto. No borra citas, teléfonos de reservas ni avisos. No se ejecutó sobre datos reales ni se activó automáticamente. |
| Outbox antiguo podía conservar `next_attempt_at` sin `available_at`. | La migración conserva el siguiente intento y prepara el campo actual, evitando dejar avisos sin fecha de procesamiento. |

## Configuración pendiente del negocio

En ambos servicios, mantener la misma configuración de reservas:

- `SERVICE_DURATIONS`: JSON con los nombres de los cuatro servicios y sus minutos,
  en múltiplos de 30. `{}` mantiene el comportamiento anterior de 30 minutos.
- `BARBERS`: turnos semanales existentes por barbero; días omitidos son descanso
  cuando se especifica `hours`. Sin `hours` continúa el horario anterior de 9 a 20,
  todos los días. No se inventaron descansos ni turnos.
- `BOOKING_MIN_NOTICE_MINUTES`: por defecto 0, conservando la regla anterior.
- `BOOKING_MAX_ADVANCE_DAYS`: sin configurar conserva el máximo sin límite anterior.
- `INBOUND_LIMIT_PER_MINUTE=20`, `MAX_PENDING_MESSAGES=40` y
  `GLOBAL_AI_TURNS_PER_MINUTE=60`: límites operativos iniciales, ajustables al volumen.

`OPENAI_MODEL` y las credenciales locales no se cambiaron.

## Despliegue: primero migración de fechas

**No hacer un despliegue gradual mezclando la versión antigua y esta versión.**
La versión anterior interpretaría los valores UTC como horas locales.

1. Respaldar PostgreSQL y probar la restauración en una base separada. La restauración
   automatizada de esta revisión usa SQLite temporal; no certifica un respaldo de Railway.
2. Ensayar esta migración con una copia de la base real y comprobar fechas conocidas,
   cantidades de citas, bloqueos, propuestas y avisos pendientes.
3. Detener los procesos anteriores de web y worker durante el mantenimiento. Conservar
   Redis y PostgreSQL; no vaciar colas ni borrar citas.
4. Con el código nuevo y `CALENDAR_UTC_MIGRATION_ENABLED=true`, ejecutar una sola vez:

   ```powershell
   python -c "from app.store.postgres import init_db; init_db()"
   ```

5. Verificar el marcador `calendar_utc_v1`, las horas locales que muestran las
   herramientas y los datos conservados. La conversión y el índice único se confirman
   en una misma transacción. Un error revierte la migración.
6. Volver a `CALENDAR_UTC_MIGRATION_ENABLED=false` y arrancar web y worker con la
   misma versión. Después verificar `/health`, `/ready`, recepción y procesamiento.

Sin habilitación explícita, una base con datos anteriores detiene el arranque con un
mensaje de mantenimiento; no se transforma silenciosamente. Una base nueva se prepara
directamente en UTC. No volver al código anterior sobre una base ya migrada; una
reversión requiere una restauración coordinada y considerar mensajes recibidos después.

## Plantillas y entrega real

- `APPOINTMENT_TEMPLATE_NAME`: nombre exacto de una plantilla aprobada para actualizaciones
  de citas, con un parámetro de texto en el cuerpo. El parámetro contiene la información
  guardada del evento; no se reconstruye desde una cita que pudiera haber cambiado.
- `SUPPORT_TEMPLATE_NAME`: plantilla aprobada independiente para solicitudes de atención
  al equipo, también con un parámetro de texto.
- `NOTIFICATION_TEMPLATE_LANGUAGE`: debe coincidir con el idioma aprobado.
- No se crearon ni aprobaron plantillas en Meta. Una variable con un nombre no demuestra
  aprobación. Probarlas con consentimiento de los destinatarios antes de usar clientes reales.
- `failed` y `uncertain` necesitan revisión. No reencolar en masa avisos inciertos: primero
  confirmar si Meta los aceptó o entregó. Un HTTP 200 no acredita lectura del destinatario.
- Los avisos ordinarios de texto conservan reintentos; no se promete entrega exactamente
  una vez si el proceso muere después de enviar pero antes de guardar el resultado.
- Mantener `AUTOMATIC_NOTICES_ENABLED=false` hasta tener plantillas, consentimiento y
  pruebas de recordatorios. El consentimiento de recordatorios no se activa por reservar.

La ventana corresponde a cada destinatario, no a la última actividad de cualquier
cliente. Véase la [política de WhatsApp Business](https://business.whatsapp.com/policy).

## Retención y operación

Definir el plazo con el responsable del negocio y actualizar el aviso de privacidad
antes de automatizar borrados. `N` representa ese plazo en días:

```powershell
python -m app.retention --days N
```

Este comando solo cuenta registros. `--apply` elimina exclusivamente los chats y logs
antiguos seleccionados; preserva conversaciones con confirmaciones pendientes vigentes.
No es un mecanismo completo para solicitudes de eliminación de todos los datos de una
persona. No se declaró cumplimiento legal ni se modificó el aviso con datos inventados.

Quedan por configurar fuera del repositorio: respaldos de producción, restauración de
PostgreSQL, monitor externo de `/ready`, alertas de webhook/worker/outbox y alertas de
gasto. Revisar los logs `outbox agotado`, `template_not_configured`, `uncertain` y el
límite global de IA; no hay un destinatario externo de alertas configurado por esta revisión.

## Verificación y límites

Resultado local: **310 pruebas aprobadas y 67 excluidas** por necesitar la ejecución
asíncrona/HTTP bloqueada en este entorno. Ruff pasó en los archivos Python modificados
y nuevos; `git diff --check` pasó. No se hizo commit, push ni despliegue desde esta revisión.

Pruebas nuevas: intento real de eludir las tres horas, cambio tardío autorizado, permisos
por barbero, confirmación que cruza el límite, solapamiento por duración, dos confirmaciones
simultáneas contra SQLite, límite de entrada, respuesta a adjuntos sin IA, autenticación de
avisos internos, migración idempotente, restauración SQLite, ventana de WhatsApp, plantillas
y retención en simulación/aplicación sobre datos sintéticos.

La suite asíncrona y los tests HTTP de FastAPI requieren sockets locales de `asyncio` en
Windows. En este entorno esa creación se bloqueó; deben ejecutarse en un entorno que lo
permita antes del despliegue. No se sustituyeron por pruebas contra servicios reales.

También siguen pendientes: concurrencia real contra PostgreSQL, ensayo de migración con
una copia de producción, pruebas WhatsApp/Meta/OpenAI de extremo a extremo, aprobación de
plantillas, integración con Google Calendar y transcripción de audios. Las pruebas locales
no certifican resistencia absoluta a prompt injection ni disponibilidad de los proveedores.
