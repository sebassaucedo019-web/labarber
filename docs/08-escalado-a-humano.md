# Escalado a humano

No es opcional — ver [05-anti-patrones.md](05-anti-patrones.md). Este template ya trae la tool `escalar_humano` (`app/agent/tools.py`) cableada a un notificador real (`app/escalation.py`) que dispara un webhook saliente. Lo único que falta configurar es a dónde.

## Esto no viene de PyWa

PyWa es un cliente de la Cloud API de Meta — manda y recibe mensajes de WhatsApp, no tiene ningún concepto de "escalar a un humano" ni de inbox de soporte. El escalado es lógica de aplicación que arma este template arriba de PyWa, no una feature de la librería.

## Buenas prácticas

- **Nunca lo dejes en un stub sin notificación real.** Un bot que "escala" pero no le avisa a nadie es peor que uno sin escalado — el usuario cree que alguien lo va a contactar y nadie lo hace.
- **Pasale contexto al humano, no solo "hubo un escalado".** El `motivo` y el `wa_id` tienen que llegar al canal — sin eso, la persona que atiende tiene que volver a preguntarle todo al usuario.
- **Confirmale al usuario que alguien lo va a contactar.** Si tenés horario de atención, decilo — "en breve te escriben" no es lo mismo de madrugada que en horario laboral.
- **Logueá cada escalado, funcione o no el webhook.** Es tu forma de auditar que nadie se quedó sin respuesta si el canal humano falla (Slack caído, alguien borró el webhook). `app/escalation.py` ya loguea como warning cuando `ESCALATION_WEBHOOK_URL` no está configurada.
- **No mezcles "avisar a un humano" con "sincronizar con el CRM".** Son cosas distintas: escalado es urgente (alguien tiene que responder ya), CRM es registro (queda guardado para después). Podés usar los dos a la vez — ver más abajo.

## El checklist: lo que necesitamos de vos

Antes de producción, definí:

- [ ] **Canal**: ¿a dónde llega el aviso? Slack, Discord, email vía n8n/Zapier, o Chatwoot.
- [ ] **`ESCALATION_WEBHOOK_URL`** en tu `.env`, apuntando a ese canal (de dónde sacar la URL según el canal, abajo).
- [ ] **Quién lo recibe y cuánto tarda en responder** — no es una variable de entorno, es un acuerdo operativo con el equipo, pero definilo antes de lanzar: afecta lo que el bot le dice al usuario.
- [ ] **Horario de cobertura**: ¿hay alguien mirando ese canal fuera de horario laboral? Si no, contemplalo en el `SYSTEM_PROMPT` (`app/agent/agent.py`) o en `context/brief-empresa.md`.
- [ ] Probaste el flujo de punta a punta al menos una vez — ver [06-checklist-pre-lanzamiento.md](06-checklist-pre-lanzamiento.md).

### De dónde sacar la URL según el canal

- **Slack**: [api.slack.com/apps](https://api.slack.com/apps) → tu app (o creá una) → Incoming Webhooks → activalo → "Add New Webhook to Workspace" → copiá la URL. Pegala tal cual en `ESCALATION_WEBHOOK_URL` — `app/escalation.py` detecta que es de Slack (`hooks.slack.com`) y arma el mensaje en el formato que Slack espera, no hace falta nada intermedio.
- **Discord**: en el canal donde querés recibir avisos → Configuración del canal → Integraciones → Webhooks → Nuevo Webhook → copiá la URL. Mismo caso: `app/escalation.py` reconoce `discord.com/api/webhooks` y lo arma solo.
- **Email**: no existe un "webhook a email" directo — acá sí hace falta un paso intermedio: un Catch Hook de n8n o Zapier que reciba el POST (formato genérico: `wa_id`, `motivo`, `timestamp`) y mande el mail. La URL que ponés en `ESCALATION_WEBHOOK_URL` es la del Catch Hook, no una dirección de correo.
- **Chatwoot**: ver [examples/escalado_chatwoot.md](../examples/escalado_chatwoot.md) — uno de los dos enfoques ahí reutiliza este mismo `ESCALATION_WEBHOOK_URL` apuntando a un flujo intermedio (n8n/Zapier) que crea la conversación en Chatwoot, igual que el caso de email.

**Por qué Slack/Discord sí funcionan directo y el resto no**: esos dos webhooks aceptan un JSON con una forma fija (`{"text": ...}` en Slack, `{"content": ...}` en Discord) y nuestro código ya sabe armarla. Cualquier otro destino (email, Chatwoot, tu CRM) necesita algo del otro lado que sepa interpretar el JSON genérico y decidir qué hacer — ahí es donde entra n8n/Zapier como traductor.

## Si además querés que quede en tu CRM

`ESCALATION_WEBHOOK_URL` es para avisar YA a un humano. Si además querés que el escalado quede registrado como evento en tu CRM (HubSpot, Pipedrive, etc.) para seguimiento posterior, sumá `examples/crm_webhook/` — son dos webhooks con destinos y propósitos distintos, se pueden usar en simultáneo. Ver [integraciones/crm.md](integraciones/crm.md).
