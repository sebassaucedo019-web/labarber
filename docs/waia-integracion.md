# WAIA: integración sobre la agenda existente

## Arquitectura y decisiones

Se conserva Python/FastAPI, SQLAlchemy/PostgreSQL, Redis/RQ y Meta Cloud API. Las
citas siguen en `appointments`; crear, confirmar, cambiar y cancelar continúa
usando las herramientas actuales. No se introduce Node ni otra base de reservas.

La agenda existente `/agenda` conserva sus enlaces de lectura. El panel `/panel`
agrega acceso independiente con usuario y contraseña, sesiones revocables en la
base, cookies HttpOnly/Secure y protección CSRF. Cada petición vuelve a comprobar
el teléfono y alcance configurados; el dueño ve todo, cada barbero solo lo suyo.

Estados: confirmed, arrived, in_service, completed, cancelled, no_show. Las
reservas arrived/in_service/completed/no_show siguen ocupando su horario original;
solo cancelled libera la reserva. Se conservan los intervalos actuales de 30 min
como duración estimada, sin inventar nuevas duraciones por servicio.

La finalización y el aviso se guardan en una misma transacción. Un sondeo durable
de la base prepara recordatorios; no depende de temporizadores por cita ni de
Redis para reconstruirlos. El outbox existente procesa los envíos. Los avisos de
turno y recordatorios comparten una clave por cita/horario/barbero para evitar
avisos equivalentes. Se revalida la cita y el consentimiento antes de enviar.

Los nuevos envíos permanecen desactivados por defecto. Las pruebas simulan Meta
y usan datos ficticios. No se activa producción ni se envían mensajes reales.

## Acceso del equipo

Abrir `https://DOMINIO_CONFIGURADO/panel`. `PUBLIC_BASE_URL` debe coincidir
exactamente con ese origen HTTPS: otro dominio no puede enviar cambios autenticados.
El panel pide usuario y contraseña una vez y conserva la sesión 30 días. No existen
contraseñas predeterminadas ni registro público. Los enlaces antiguos `/agenda`
siguen siendo de lectura; no otorgan permisos de edición del panel.

En una consola privada del servicio, con las variables del entorno y la base
correcta, ejecutar:

```sh
python -m app.staff_account obed NUMERO_CONFIGURADO_DE_OBED
python -m app.staff_account administrador NUMERO_CONFIGURADO_DEL_DUENO
```

El comando solicita la contraseña sin mostrarla (mínimo 12 caracteres); no se
pasa en argumentos, chat ni Git. Ejecutarlo otra vez restablece el acceso y revoca
sus sesiones. Agregar `--disable` desactiva el usuario y revoca sus sesiones.
El teléfono debe seguir figurando en el directorio del equipo. Si un teléfono es
del dueño y de un barbero, prevalece el permiso del dueño. Quitar el teléfono de
la configuración también invalida el acceso en la siguiente petición.

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

| Estado actual | Cambios permitidos en el panel |
| --- | --- |
| Confirmada | Llegó, En atención, Atendido, No asistió |
| Llegó | Deshacer llegada, En atención, Atendido |
| En atención | Atendido |
| Atendido, Cancelada, No asistió | Terminales |

La llegada se registra el mismo día, desde dos horas antes. En atención y Atendido
solo desde el inicio reservado. No asistió requiere al menos 15 minutos de espera.
Deshacer llegada borra la marca actual, conservando el evento de auditoría.
Las cancelaciones siguen en el flujo existente de WhatsApp con confirmación y
permisos del equipo; el panel no incorpora un segundo motor de cancelación.

Solo el administrador puede bloquear/desbloquear intervalos. Se rechazan
solapamientos con citas o bloqueos. El bot consulta estos mismos bloqueos al
mostrar disponibilidad, agendar y reagendar. Los cambios de estado no liberan
accidentalmente un horario reservado. Las operaciones usan el mismo bloqueo de
transacción que las reservas para evitar carreras entre panel y bot.

## Consentimiento y mensajes

No se presume permiso por disponer del teléfono. Cada cita inicia sin consentimiento
para los nuevos avisos. El equipo registra un permiso real y su evidencia desde
la tarjeta de la cita; puede revocarlo. No inventar evidencia ni habilitarlo en masa.
`BAJA`, `STOP`, `NO RECORDATORIOS` o `NO QUIERO RECORDATORIOS` recibidos por el
webhook firmado revocan el consentimiento y anulan los avisos pendientes.
`ALTA RECORDATORIOS` elimina la baja global, pero no reactiva silenciosamente
permisos de citas anteriores: deben registrarse de nuevo. El panel impide que el
equipo pase por alto una baja aún activa.

La política de [WhatsApp Business](https://whatsappbusiness.com/policy/) requiere
permiso y plantillas aprobadas para iniciar conversaciones fuera de la ventana
de atención. Estos nuevos avisos usan siempre plantillas, incluso dentro de ella;
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

Mantener el flag en `false` hasta contar con autorización para la prueba real.
Este flag controla únicamente los dos tipos nuevos: no apaga las respuestas ni
las confirmaciones existentes del bot. Las variables deben coincidir en web y
worker. Nunca subir tokens a Git ni escribirlos en el documento.

## Temporización, recuperación y entrega

- El worker consulta la base cada 5 segundos con el hilo outbox existente.
  Tras reinicio reconstruye recordatorios de las citas; no requiere cron nuevo.
- Recordatorios: de 30 a 5 minutos antes. Una cita creada/reagendada a menos de
  30 minutos no recibe este recordatorio; ya tiene su confirmación habitual.
- Atendido: analiza la siguiente cita activa del mismo barbero. No salta sobre
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
  fallas de WhatsApp. El administrador puede consultar pendientes, envíos y
  errores en Seguimiento de notificaciones.

## Despliegue y comprobación

1. Respaldar PostgreSQL. Desplegar web y worker con la misma versión, con avisos
   desactivados. No mezclar workers antiguos que no conocen los nuevos estados.
2. `init_db` agrega tablas, columnas e índice, sin borrar citas, chats ni outbox.
   PostgreSQL serializa inicializaciones simultáneas. Si existen reservas
   duplicadas que impiden crear el índice, falla el inicio conservando los datos:
   revisar esos conflictos antes de continuar.
3. Verificar `/health`, crear accesos privados con el comando anterior, probar
   en HTTPS que cada barbero ve solo lo suyo y que el dueño ve todas las agendas.
4. Confirmar que las citas del bot aparecen en el panel y sus bloqueos se respetan.
   Comprobar los eventos y pendientes con datos de prueba.
5. Tras autorización, usar destinatarios de prueba con consentimiento y plantillas
   aprobadas. Activar el flag, verificar tanto aceptación como callback de entrega,
   probar baja, reprogramación y reinicio. Solo entonces habilitar uso comercial.
6. Para detener nuevos avisos, poner el flag en `false` y desplegar ambos servicios.
   Las reservas y los cambios de estado continúan funcionando. No borrar la cola.

La PWA apunta a `/panel`, sin tokens en URL. No almacena agendas de clientes en
caché; sin conexión informa que hay que conectarse y no permite cambios locales.
Android/iOS pueden ofrecer Agregar a inicio; la instalación en teléfonos reales
se debe comprobar por separado. El panel refresca cada 15 s y al volver a la
pestaña, sin interrumpir formularios que se estén escribiendo.

Pruebas locales: `uv run pytest -q`, `uv run ruff check app tests --select F,E9,B,UP`
y `node --check app/static/agenda/panel.js`. La suite bloquea HTTP/LLM reales y
usa SQLite, Redis simulado y números ficticios. Incluye concurrencia, reinicio,
migración de datos anteriores, aislamiento de barberos, CSRF, caducidad/revocación,
errores del proveedor, deduplicación y callbacks. La comprobación de PostgreSQL
y de Meta en Railway es una etapa adicional; no equivale a los tests locales.
