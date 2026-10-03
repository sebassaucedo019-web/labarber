# ¿Número nuevo o Coexistence?

Hay dos caminos para conectar un número de WhatsApp a este bot. La diferencia importa antes de arrancar — no es trivial cambiar de uno a otro después.

## Los dos caminos

| | Número nuevo (lo que asume este template) | Coexistence |
|---|---|---|
| Qué es | Un número sin cuenta de WhatsApp previa, dado de alta directo en Cloud API | Conectás la Cloud API a un número que **ya tiene** la app de WhatsApp Business activa, con historial y conversaciones reales, sin perder nada de eso |
| Setup | El que ya documenta este repo — [02-configuracion-meta.md](02-configuracion-meta.md) | Requiere el estado de **Tech Provider** (no hace falta ser Solution Partner — ver más abajo) + Embedded Signup — bastante más setup que este template por sí solo |
| Límite de mensajes | El normal de Cloud API | **20 mensajes/segundo** mientras Coexistence está activo — mucho más bajo |
| Funciones que se pierden | Ninguna | Mensajes efímeros/view-once, ubicación en vivo, catálogos, pedidos, estados, grupos quedan deshabilitados o solo-lectura |
| Riesgo específico | Ninguno nuevo | **Doble respuesta**: si un humano contesta desde la app mientras tu bot contesta por la API, el cliente recibe dos respuestas distintas — Meta no lo resuelve solo, necesitás tu propia lógica de pausa/handoff |
| Cuándo elegirlo | Default: estás armando un bot nuevo, no tenés un número con historial que preservar | Solo si tenés una razón de negocio real para preservar un número específico con conversaciones ya activas |

## ¿Es obligatorio? Sí — pero no es un club cerrado

Sin ser Tech Provider o Solution Partner, Meta directamente no te deja arrancar el Embedded Signup de Coexistence — es un gate técnico real, no una recomendación, y no hay atajo conocido. La buena noticia: **Tech Provider no hace falta ser Solution Partner**, y es autoservicio, no un programa de partners con aprobación comercial:

1. App Dashboard → Use cases → Customize (WhatsApp) → "Tech Provider onboarding".
2. Requiere tu Business Portfolio **verificado** (verificación estándar, no algo especial).
3. Pasás App Review pidiendo acceso avanzado a `whatsapp_business_messaging` y `whatsapp_business_management` (con videos mostrando envío de mensajes y creación de templates). Meta no publica un plazo fijo de aprobación.
4. El dashboard tiene un botón explícito **"Onboard without a partner"** — confirma que no necesitás pasar por ningún Solution Partner externo.

**Lo que no pudimos confirmar con 100% de certeza**: la documentación de Meta está redactada asumiendo un modelo "proveedor → clientes" (como si fueras a ofrecer esto a otros negocios), y no vimos una frase explícita que confirme que podés pedir Tech Provider siendo tu propio único "cliente". Tampoco vimos ninguna prohibición de eso. Si te aparece algo ambiguo en el App Review por esto, es el punto donde preguntarle directo al soporte de Meta for Developers.

## Por qué este template asume número nuevo por default

Todo lo que ya está armado acá (`app/`, docs, checklist) asume número nuevo — es la ruta más simple y no tiene ninguna de las limitaciones de arriba, ni la vuelta de Tech Provider + App Review. Si tu caso es "tengo un número de WhatsApp Business que mi equipo ya usa a mano y quiero sumarle un bot sin perder el historial", Coexistence es la respuesta técnica correcta y **es accesible sin ser una empresa grande** — pero seguís necesitando construir vos mismo la lógica para que el bot y los humanos no se pisen (por ejemplo, que el bot se calle apenas un humano toca la conversación desde la app — eso no viene armado en `app/agent/agent.py`, es trabajo adicional).

## Fuentes oficiales

- [Onboard WhatsApp Business app users (Coexistence) — Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/onboarding-business-app-users/)
- [Solution Partner overview — Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/overview)
- [Become a Tech Provider — Meta for Developers](https://developers.facebook.com/documentation/business-messaging/whatsapp/solution-providers/get-started-for-tech-providers)

El límite de mensajes/segundo y la disponibilidad por país los actualiza Meta sin versión fija — confirmalos directo en tu Business Manager antes de decidirte, no asumas que los números de esta página siguen exactos.
