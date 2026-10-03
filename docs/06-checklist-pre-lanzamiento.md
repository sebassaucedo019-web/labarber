# Checklist de pre-lanzamiento

- [ ] Cuenta de Meta Business **verificada** (tarda; empezá pronto)
- [ ] Número dedicado, sin WhatsApp previo, con display name aprobado
- [ ] Plantillas necesarias enviadas y aprobadas (ver [05-anti-patrones.md](05-anti-patrones.md))
- [ ] Token permanente de System User cargado en `WHATSAPP_ACCESS_TOKEN` (no el token temporal de 24h del dashboard)
- [ ] Webhook registrado contra dominio permanente, firma verificada (`app/webhook/signature.py`) — el número de producción nunca apunta a un túnel, ver [07-entornos-test-vs-produccion.md](07-entornos-test-vs-produccion.md)
- [ ] Suscripción a los campos correctos (`messages`, y `message_template_status_update` si usás plantillas)
- [ ] Cola y worker separados, corriendo ambos (`app` + `worker`), con dedupe e idempotencia probados
- [ ] Debounce verificado mandando tres mensajes seguidos
- [ ] Monitorización externa contra `/health` (Uptime Kuma, Better Stack u otro) — enterate vos antes que Meta
- [ ] Alertas de gasto: tokens del modelo y mensajes de Meta
- [ ] `ESCALATION_WEBHOOK_URL` configurada y probada de punta a punta (ver [08-escalado-a-humano.md](08-escalado-a-humano.md)) — sin esto `escalar_humano` no le avisa a nadie
- [ ] Aviso de privacidad y mecanismo de opt-out (`STOP` / `BAJA`) funcionando
- [ ] Plan para el cambio de facturación del 1 de octubre de 2026 — revisar tarifas exactas apenas se publiquen (1 de septiembre de 2026, ver [03-pricing-y-costos.md](03-pricing-y-costos.md))
