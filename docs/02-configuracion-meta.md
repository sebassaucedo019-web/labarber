# Configuración en Meta

Esto no es un tutorial paso a paso de la UI de developers.facebook.com — cambia cada pocos meses y desactualiza cualquier captura de pantalla en cuestión de semanas. La fuente correcta es la documentación oficial. Acá tenés los links y el checklist de qué configurar.

## Documentación oficial

- WhatsApp Business Platform (Cloud API): https://developers.facebook.com/docs/whatsapp/cloud-api
- Meta for Developers (crear app, credenciales): https://developers.facebook.com/apps
- Configuración de webhooks: https://developers.facebook.com/docs/whatsapp/cloud-api/guides/set-up-webhooks
- Business Manager (System Users, tokens permanentes): https://business.facebook.com/settings/system-users
- Precios de la plataforma: https://developers.facebook.com/docs/whatsapp/pricing
- WhatsApp Business Messaging Policy: https://developers.facebook.com/docs/whatsapp/policy

## Checklist de configuración

- [ ] App creada en developers.facebook.com con el producto WhatsApp agregado
- [ ] Decidir número de prueba (para desarrollo, gratis, limitado a destinatarios verificados manualmente) vs. número real dedicado — nunca tu número personal (ver [05-anti-patrones.md](05-anti-patrones.md) y el flujo completo en [07-entornos-test-vs-produccion.md](07-entornos-test-vs-produccion.md))
- [ ] Si el número de producción ya tiene WhatsApp Business activo con historial que querés preservar: decidir entre número nuevo o Coexistence antes de seguir — ver [09-numero-nuevo-o-coexistencia.md](09-numero-nuevo-o-coexistencia.md)
- [ ] System User creado en Business Manager con token **permanente** — el token de 24h del dashboard no sirve para producción → `WHATSAPP_ACCESS_TOKEN`
- [ ] ID del número de teléfono copiado desde API Setup → `WHATSAPP_PHONE_NUMBER_ID`
- [ ] App Secret copiado desde la configuración básica de la app → `META_APP_SECRET`
- [ ] Verify token definido por vos (cualquier string) y cargado igual en Meta y en tu `.env` → `META_WEBHOOK_VERIFY_TOKEN`
- [ ] Webhook registrado apuntando a tu `callback_url` (túnel en desarrollo, dominio permanente en producción — ver [scripts/dev_tunnel.md](../scripts/dev_tunnel.md) y [04-despliegue.md](04-despliegue.md))
- [ ] Suscripción del webhook al campo `messages` (y `message_template_status_update` si vas a usar plantillas)
- [ ] Si tu bot inicia conversaciones: plantillas enviadas a revisión (tardan, empezá temprano)

Los nombres de variables de arriba son los mismos que en `.env.example` de este repo.
