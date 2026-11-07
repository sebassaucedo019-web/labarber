# Operación de citas por WhatsApp

## Estado actual

La interfaz web propia fue retirada: `/agenda`, `/panel`, `/api/agenda`, los
assets y la PWA ya no forman parte del servicio. También se retiraron el comando
`app.staff_account`, la herramienta de enlaces temporales y `PUBLIC_BASE_URL`.
Los enlaces enviados anteriormente dejan de abrir una agenda; no se convierten
en accesos de Google.

La integración con Google Calendar está pendiente. Retirar la interfaz no copia
citas ni activa sincronización. Las reservas y consultas continúan usando la
base existente. Este documento conserva su ruta anterior para mantener los enlaces
desde otras guías.

## Arquitectura y decisiones

Se conserva Python/FastAPI, SQLAlchemy/PostgreSQL, Redis/RQ y Meta Cloud API. Las
citas siguen en `appointments`; crear, confirmar, cambiar y cancelar continúa
usando las herramientas actuales. No se introduce Node ni otra base de reservas.

Los permisos del equipo se comprueban por el teléfono configurado: el dueño ve
todas las citas y cada barbero solo las propias. No dependen de cuentas web ni de
lo que el remitente diga ser.

Estados: confirmed, arrived, in_service, completed, cancelled, no_show. Las
reservas arrived/in_service/completed/no_show siguen ocupando su horario original;
solo cancelled libera la reserva. Se conservan los intervalos actuales de 30 min
como duración estimada, sin inventar nuevas duraciones por servicio.

Las reservas y sus avisos se guardan en una misma transacción. Un sondeo durable
de la base prepara recordatorios; no depende de temporizadores por cita ni de
Redis para reconstruirlos. El outbox existente procesa los envíos. Los avisos de
turno y recordatorios comparten una clave por cita/horario/barbero para evitar
avisos equivalentes. Se revalida la cita y el consentimiento antes de enviar.

`AUTOMATIC_NOTICES_ENABLED=false` es el valor predeterminado para recordatorios y
avisos de próximo turno. No desactiva las confirmaciones del bot ni su outbox.
La retirada no habilita envíos automáticos ni modifica consentimientos.

## Acceso del equipo

El equipo consulta la agenda y la siguiente cita por WhatsApp. El menú conserva
Ver citas, Agregar cita y Cancelar cita; la consulta devuelve un resumen por chat.
Los botones antiguos se interpretan por identificador y no conceden permisos
a quien los reenvía. Pedir un enlace no debe generar una URL de la interfaz retirada.

Para registrar citas se requiere nombre y teléfono del cliente, servicio, fecha,
hora y confirmación en otro mensaje. El barbero registra solo en su agenda; el
dueño elige el barbero. Las cancelaciones también requieren identificar la cita
y confirmar. Los clientes solo gestionan sus propias reservas.

Si un teléfono es del dueño y de un barbero, prevalece el permiso del dueño.
Las antiguas cuentas y sesiones web no conceden acceso a WhatsApp ni a Google.

## Directorio y horarios

Sin `BARBERS`, se conservan Obed, Jesús y Yadier y las variables `BARBER_*_WA_ID`.
`OWNER_WA_ID` identifica al administrador. Un teléfono vacío no habilita acceso.
Los teléfonos inválidos se rechazan al arrancar; no se corrigen ni inventan.

Para otro equipo, `BARBERS` acepta una lista JSON. Sustituye el directorio completo,
no añade elementos al anterior. Ejemplo con un número ficticio:

```json
[{"name":"Luis","phone":"525500000001","hours":{"0":[[540,780],[840,1200]],"1":[[600,1140]]}}]
```

Los días son `0` lunes a `6` domingo; los horarios son minutos desde medianoche,
en intervalos de 30 minutos. En el ejemplo: lunes 09–13 y 14–20; martes 10–19.
Si se especifica `hours`, los días omitidos están cerrados. Si no se especifica,
se mantiene 09–20 todos los días. Cambiar el nombre de un barbero con citas
existentes requiere una migración explícita: no renombrarlo como si fuera uno nuevo.
La zona del negocio continúa siendo `America/Chihuahua`; cambiar de ciudad exige
revisar también las fechas históricas. La duración permanece estimada en 30 min.

## Estados y bloqueos

Las reglas de `app/scheduling.py` y los datos de estado se conservan. Al retirar
el panel ya no hay una interfaz operativa para registrar llegada, inicio,
finalización o inasistencia, ni para crear o quitar bloqueos. Estas funciones no
se incorporan automáticamente al chat ni a Google Calendar.

| Estado actual | Transiciones conservadas en el motor |
| --- | --- |
| Confirmada | Llegó, En atención, Atendido, No asistió |
| Llegó | Deshacer llegada, En atención, Atendido |
| En atención | Atendido |
| Atendido, Cancelada, No asistió | Terminales |

La llegada se registra el mismo día, desde dos horas antes. En atención y Atendido
solo desde el inicio reservado. No asistió requiere al menos 15 minutos de espera.
Deshacer llegada borra la marca actual, conservando el evento de auditoría.
Las cancelaciones siguen en el flujo existente de WhatsApp con confirmación y
permisos del equipo.

El motor reserva al administrador la creación de bloqueos y rechaza solapamientos
con citas o bloqueos. Los bloqueos existentes siguen restringiendo la disponibilidad
al consultar, agendar y reagendar, aunque su interfaz de administración se haya
retirado. No borrarlos para recuperar horarios sin revisar su propósito. Los cambios
de estado no liberan un horario reservado. Se conserva el bloqueo de transacción
compartido con las reservas y el índice que impide duplicar un horario.

## Consentimiento y mensajes

No se presume permiso por disponer del teléfono. Cada cita inicia sin consentimiento
para los avisos automáticos. Los consentimientos y evidencias existentes se
conservan; al retirar el panel no queda una interfaz para registrar permiso por
cita. Una futura integración deberá proporcionarla antes de ofrecer ese flujo.
No inventar evidencia ni habilitarlo en masa.
`BAJA`, `STOP`, `NO RECORDATORIOS` o `NO QUIERO RECORDATORIOS` recibidos por el
webhook firmado revocan el consentimiento y anulan los avisos pendientes.
`ALTA RECORDATORIOS` elimina la baja global, pero no reactiva silenciosamente
permisos de citas anteriores ni concede permiso a nuevas citas. El envío sigue
comprobando tanto el consentimiento por cita como la baja global.

Los comandos se ordenan por su fecha de envío en WhatsApp, no por el orden de
llegada al servidor. Los reintentos antiguos no reemplazan una decisión posterior;
si un alta y una baja tienen el mismo segundo, prevalece la baja. Una solicitud
de alta sin fecha válida nunca rehabilita permisos. Para bajas anteriores que no
tenían fecha registrada se exige una solicitud de alta reciente.

La política de [WhatsApp Business](https://whatsappbusiness.com/policy/) requiere
permiso y plantillas aprobadas para iniciar conversaciones fuera de la ventana
de atención. Estos avisos usan siempre plantillas, incluso dentro de ella;
no hay sustitución por texto libre si falta la plantilla.

Crear y obtener aprobación en Meta de dos plantillas con tres parámetros en el
cuerpo, en este orden: **nombre del cliente, nombre del negocio, hora reservada**.
Sin cabecera ni botones con parámetros adicionales. Textos propuestos:

```text
Recordatorio:
Hola, {{1}}. Te recordamos que hoy tienes una cita en {{2}} a las {{3}}.
¡Te esperamos! Para dejar de recibir recordatorios, responde BAJA.

Próximo turno:
Hola, {{1}}. Tu cita en {{2}} está próxima, a las {{3}}.
Tu barbero ya terminó su servicio anterior. ¡Te esperamos!
Para dejar de recibir recordatorios, responde BAJA.
```

Configurar **los nombres y el idioma efectivamente aprobados**, no asumir que los
ejemplos ya están aprobados:

```dotenv
AUTOMATIC_NOTICES_ENABLED=false
BUSINESS_NAME=BARBER CG
REMINDER_TEMPLATE_NAME=
TURN_TEMPLATE_NAME=
NOTIFICATION_TEMPLATE_LANGUAGE=es_MX
```

Mantener el flag en `false` hasta validar el flujo de consentimiento y contar con
plantillas aprobadas y autorización para una prueba real. Este flag controla
únicamente recordatorios y próximo turno: no apaga las respuestas ni las
confirmaciones existentes del bot. Las variables deben coincidir en web y worker.
Nunca subir tokens a Git ni escribirlos en el documento.

## Temporización, recuperación y entrega

- El worker consulta la base cada 5 segundos con el hilo outbox existente.
  Tras reinicio reconstruye recordatorios de las citas; no requiere cron nuevo.
- Recordatorios: de 30 a 5 minutos antes. Una cita creada/reagendada a menos de
  30 minutos no recibe este recordatorio; ya tiene su confirmación habitual.
- Al ejecutar la transición a Atendido, el motor analiza la siguiente cita activa
  del mismo barbero. El disparador operativo del panel fue retirado; conservar
  esta función no crea una nueva forma de marcar Atendido. No salta sobre
  un cliente presente/en atención para avisar al de después. Solo prepara el
  aviso si faltan de 0 a 30 minutos. Nunca cambia la hora ni ofrece adelantarla.
- Ambos avisos comparten clave por cita, horario, barbero y destinatario. Un
  aviso reciente aceptado/en proceso/incierto también evita duplicación tras
  un cambio de última hora. Revertir una llegada no repite avisos ya cancelados
  de ese mismo horario.
- Antes del envío se comprueban otra vez el estado, horario, barbero, teléfono,
  consentimiento y baja. Cancelar/reagendar invalida los pendientes anteriores.
- HTTP 429/5xx: reintentos con espera creciente (15 s, 60 s, 5 min, 15 min, 1 h),
  máximo 8, siempre sujetos a que la cita aún corresponda. Otros errores HTTP
  son fallos definitivos. Un error de plantillas aparece como
  `template_not_configured` y requiere corregir la configuración.
- Un timeout, una aceptación sin identificador o un reinicio durante el envío
  deja el resultado **incierto**. No se reenvía a ciegas. Consultar al proveedor
  antes de cualquier intervención; no resetear filas para forzar duplicados.
- `sent` significa aceptada por Meta con identificador; `delivered` y `read`
  solo se registran al recibir el estado firmado de Meta. Los estados no
  retroceden por callbacks fuera de orden. No se garantiza entrega exactamente
  una vez a través de una red externa.
- El cambio a Atendido queda confirmado antes del envío y no se revierte por
  fallas de WhatsApp. El seguimiento se conserva en `notification_outbox` y los
  logs; la pantalla de seguimiento fue retirada. Consultar [outbox.md](outbox.md).

El prefijo `waia:` de `biz_opaque_callback_data` sigue identificando los avisos
en los callbacks de Meta. No es una dependencia de la interfaz: se conserva para
reconocer estados de entrega, incluidos los de mensajes enviados antes de la retirada.

## Despliegue y comprobación

1. Respaldar PostgreSQL. Desplegar web y worker con la misma versión, con
   `AUTOMATIC_NOTICES_ENABLED=false`. No dejar procesos antiguos generando enlaces.
2. La retirada no requiere `DROP`, recrear tablas ni vaciar Redis. Conservar citas,
   conversaciones, confirmaciones pendientes, eventos, bloqueos, consentimientos,
   outbox y tablas de cuentas/sesiones antiguas. `init_db` mantiene la inicialización
   aditiva y el índice de reservas; los conflictos deben revisarse sin borrar datos.
3. Quitar `PUBLIC_BASE_URL` de la configuración de despliegue: solo servía a la UI.
   Conservar los secretos de Meta, el directorio del equipo y las variables de
   reservas y avisos. Verificar `/health`, `/ready` y el worker.
4. Comprobar que las rutas retiradas ya no exponen agendas ni permiten escrituras,
   incluso con enlaces o cookies antiguos. No reenviar tokens antiguos a Google.
   Mantener la ocultación de parámetros de consulta en logs, también por el webhook.
5. Revisar el comportamiento de historiales con enlaces antiguos y de respuestas
   de WhatsApp pendientes en Redis. No vaciar lotes ni deduplicación para retirarlos:
   eso podría perder mensajes o repetir operaciones ya guardadas.
6. Con datos de prueba, comprobar reservas y confirmaciones, permisos del equipo,
   botones antiguos, resúmenes por chat, horarios y bloqueos, cancelación,
   reagendado, recuperación del outbox y recepción de estados de entrega.
7. Los avisos automáticos requieren una validación aparte de consentimiento,
   plantillas, baja, reprogramación, reinicio y entrega. Poner el flag en `false`
   detiene su envío; no borrar la cola ni los pendientes de confirmación.

Pruebas locales del backend: `uv run pytest -q` y
`uv run ruff check app tests --select F,E9,B,UP`. La suite bloquea HTTP/LLM reales
y usa SQLite, Redis simulado y números ficticios. La validación de PostgreSQL
y de Meta en Railway es una etapa adicional. Esta actualización documental no
certifica el resultado de esas comprobaciones ni una migración a Google Calendar.
