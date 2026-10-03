# Anti-patrones: qué NO hacer

## 1. Baileys, whatsapp-web.js u OpenWA (APIs no oficiales)

Conectan por QR sin pagar por mensaje, por eso llenan los tutoriales de YouTube. Ojo con dos cosas que se suelen mezclar mal:

- Usar librerías no oficiales **siempre** violó los Términos de Servicio generales de WhatsApp — no es una regla nueva de 2026.
- Sí hay una política nueva, pero es otra cosa: desde el 15 de enero de 2026 (política de "AI Providers", vigente desde el 16 de febrero de 2026, actualizada el 12 de mayo de 2026) Meta prohíbe explícitamente que empresas cuyo **producto primario es IA de propósito general** (tipo OpenAI, Perplexity) usen la **API oficial** como canal de distribución de su producto. No tiene nada que ver con Baileys/QR, y **no aplica** a un bot de negocio que usa IA como funcionalidad secundaria — que es el caso de este template. No te asustes con esa fecha si tu bot es "atención al cliente con IA", no "vendemos acceso a un LLM".

Dicho eso, la recomendación se mantiene: para un experimento personal, una API no oficial puede valer. Para un negocio, es construir sobre arena — el plazo de "2 a 8 semanas antes del baneo" que corre en foros es consenso de la industria, no un dato oficial de Meta, pero el riesgo de que tu número quede inutilizable sin aviso previo es real y no vale la pena para algo que genera ingresos.

## 2. Llamar al LLM dentro del handler del webhook

El error #1. Ver [01-arquitectura.md](01-arquitectura.md): la primera respuesta lenta dispara los reintentos de Meta y el usuario recibe la misma respuesta duplicada.

## 3. Usar tu número personal de WhatsApp

Tu número personal —el que usás con amigos y familia— no tiene forma limpia de convertirse en el número de un bot: no lo hagas. Para un número de *negocio* que ya está en uso (con clientes reales, no tu vida personal), la cosa cambia: existe **Coexistence**, que te deja conectar la Cloud API sin perder ese número ni su historial — pero es un camino con bastante más complejidad y limitaciones que arrancar con un número nuevo. Ver [09-numero-nuevo-o-coexistencia.md](09-numero-nuevo-o-coexistencia.md) antes de decidir. Por default, este template asume número nuevo.

## 4. Free tier que duerme

Cold start de casi un minuto = webhooks fallidos = calidad de número degradada. Ver [04-despliegue.md](04-despliegue.md) para las opciones que no tienen este problema.

## 5. Un árbol de decisión con LLM encima

O usás el modelo para llevar la conversación (como está armado en `app/agent/agent.py`: historial + system prompt + tools), o usás un flujo determinista. Mezclar los dos da lo peor de ambos mundos: rígido e impredecible a la vez.

## 6. Bot sin salida a humano

La tool `escalar_humano` (`app/agent/tools.py`) no es opcional, y ya viene conectada a un notificador real (`app/escalation.py`) — lo único que falta sos vos: configurar `ESCALATION_WEBHOOK_URL`. Sin esa variable, el escalado no le avisa a nadie, solo queda en el log. Ver [08-escalado-a-humano.md](08-escalado-a-humano.md).

## 7. Prometer privacidad que no podés dar

Todos los mensajes pasan por la infraestructura de Meta. Podés self-hostear tu aplicación, tus datos y hasta el modelo (Ollama/vLLM), pero no WhatsApp. Si el requisito real es que los mensajes no toquen a un tercero, WhatsApp no es el canal.

## 8. Dejar las plantillas para el final

La aprobación tarda y Meta las rechaza por detalles de formato. Si tu bot inicia conversaciones, mandalas a revisión en la primera semana — no cuando ya las necesitás. Ver [02-configuracion-meta.md](02-configuracion-meta.md).
