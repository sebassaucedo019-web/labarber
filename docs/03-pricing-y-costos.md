# Pricing y costos

Fuente primaria: [documentación oficial de precios](https://developers.facebook.com/docs/whatsapp/pricing). Lo de acá es el resumen con lo confirmado a agosto 2026 — antes de presupuestar en serio, confirmá contra esa página, no contra este archivo.

## Modelo actual: pago por mensaje entregado

Desde julio de 2025, Meta cobra **por mensaje entregado**, no por conversación de 24h. Los mensajes entrantes (los que manda el usuario) son gratis siempre.

Presupuesto = (mensajes salientes × tarifa del país) + (tokens del modelo × precio del modelo) + hosting.

Consecuencia de diseño directa: si tu bot contesta en cinco mensajitos cortos en vez de uno consolidado, pagás cinco veces el costo de mensajería por la misma respuesta. El system prompt de este template ya instruye al agente a consolidar (`app/agent/agent.py`, `SYSTEM_PROMPT`) — no lo saques sin reemplazarlo por algo equivalente.

## Cambio del 1 de octubre de 2026

La ventana de servicio deja de ser gratuita: los mensajes de texto libre dentro de la ventana y las plantillas de utilidad *in-window* pasan a cobrarse a la tarifa del país de destino.

**Tarifas exactas: pendiente de confirmar.** Meta las publica el 1 de septiembre de 2026. Hasta esa fecha no hay cifra oficial — no la inventes en tu presupuesto, dejá margen y revisalo apenas se publique (ver [06-checklist-pre-lanzamiento.md](06-checklist-pre-lanzamiento.md)).

## Meta Business Agent — no es parte de tu bot

Ojo con confundir esto: **Meta Business Agent** es un producto separado y opcional de Meta, no un SDK que uses dentro de tu bot. Es un agente de IA propio de Meta, no-code, que se activa desde la app de WhatsApp Business o, para empresas, vía la "Business Agent Platform" (disponible desde julio de 2026).

- Pricing confirmado: **USD 2 por millón de tokens**, vigente desde el 1 de agosto de 2026 (hubo trial gratis en julio de 2026).
- No es un costo de este template ni de tu agente custom (Pydantic AI + OpenAI en `app/agent/agent.py`) — es el costo si vos, o alguien con acceso al número, activa el producto de Meta.

**Advertencia:** no hay claridad oficial de qué pasa si el mismo número tiene tu bot custom corriendo *y* alguien activa Meta Business Agent — hay riesgo real de que ambos contesten y se dupliquen respuestas. No mezcles los dos en el mismo número.

## Costo del modelo

Aparte de la mensajería, pagás tokens del LLM (`OPENAI_API_KEY` / `OPENAI_MODEL` en tu `.env`). Ese costo depende del modelo que elijas — ver [faq.md](faq.md) para cómo cambiarlo sin tocar código.
