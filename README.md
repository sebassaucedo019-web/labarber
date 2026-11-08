# Red Level Barber WhatsApp Bot

Agente de WhatsApp para atender clientes, consultar servicios, gestionar citas,
reagendar y aplicar la política de cancelación configurada.

Adaptación en curso para **Red Level Barber**. El nombre está confirmado;
catálogo, precios, ubicación, horarios, equipo, contactos y reglas del nuevo
negocio están pendientes. El motor conserva los valores anteriores hasta su
confirmación. Esta preparación local no cambia la instalación de Railway.

`BUSINESS_NAME` controla la marca en saludos, instrucciones del agente,
confirmaciones, avisos al equipo y la página de privacidad.

La interfaz web propia de agenda fue retirada, incluidos panel, acceso web del equipo
y enlaces temporales. La integración con Google Calendar sigue pendiente; no hay
sincronización ni enlaces de Google disponibles todavía.

Se conservan las reservas, roles, horarios, resúmenes del equipo por WhatsApp y
datos existentes, sin borrar tablas. El outbox de confirmaciones sigue operativo;
los recordatorios y avisos de próximo turno mantienen
`AUTOMATIC_NOTICES_ENABLED=false` por defecto.

Configuración y límites actuales: [Operación de citas](docs/waia-integracion.md).
