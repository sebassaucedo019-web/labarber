# Preguntas frecuentes

## ¿Por qué Python y no Node?

No por ideología: PyWa no tiene equivalente real en Node para esto (envío, verificación de firma, Flows cifrados, CLI). Este template además usa Pydantic AI para el agente — mismo estilo de tipado que FastAPI, tool calling tipado con menos boilerplate. Si tu equipo vive en TypeScript a diario, `whatsapp-api-js` es una alternativa legítima — perder una semana peleando con Python cuesta más de lo que ahorra.

## ¿Por qué la cola no es opcional?

Porque Meta reintenta el webhook si no le contestás 200 rápido, y si el LLM corre dentro del handler, esos reintentos te duplican (o triplican) la respuesta al usuario. El detalle completo está en [01-arquitectura.md](01-arquitectura.md).

## ¿Qué pasa si mi número ya tenía WhatsApp antes?

No lo uses. El número debe estar libre de cuenta previa antes de darlo de alta en Cloud API — migrar uno en uso es doloroso y a veces irreversible. Ver [05-anti-patrones.md](05-anti-patrones.md).

## ¿Cómo pruebo esto sin gastar en producción?

Meta te da un número de prueba gratis al crear la app (limitado a destinatarios verificados manualmente). Los mensajes entrantes son gratis siempre, así que probar el flujo completo con ese número no te cuesta mensajería — solo pagás los tokens del LLM que uses en las pruebas. Ver [02-configuracion-meta.md](02-configuracion-meta.md) y la v1 en [00-ruta-de-construccion.md](00-ruta-de-construccion.md).

## ¿El túnel de desarrollo (ngrok/Cloudflare Tunnel) pone en riesgo mi número?

No hay casos documentados de que un túnel banee una cuenta de WhatsApp Business — lo investigamos específicamente y no aparece. El riesgo real es no verificar la firma del webhook (este template ya lo hace) y usar el número de producción para probar en vez del número de prueba. Detalle completo, incluyendo qué cambió con ngrok en 2026, en [scripts/dev_tunnel.md](../scripts/dev_tunnel.md) y [07-entornos-test-vs-produccion.md](07-entornos-test-vs-produccion.md).

## ¿Qué es Meta Business Agent y me afecta?

Es un producto de IA separado y opcional de Meta, no algo que uses dentro de tu bot. No te afecta si no lo activás vos (o alguien con acceso al número) en el mismo número que tu bot custom. Detalle completo en [03-pricing-y-costos.md](03-pricing-y-costos.md).

## ¿Cómo elijo qué ejemplos de `examples/` copiar?

Depende de tu caso de uso, no de "copiar todo por las dudas" — cada ejemplo agrega dependencias y superficie de mantenimiento. La guía está en [00-ruta-de-construccion.md](00-ruta-de-construccion.md): Flows si capturás datos estructurados, audio si recibís notas de voz, CRM si necesitás avisar a un sistema externo, Chatwoot si el email no te alcanza como inbox de escalado.

## ¿Cómo cambio el modelo de OpenAI?

Cambiá `OPENAI_MODEL` en tu `.env` — no está fijado en el código a propósito, porque los modelos disponibles cambian seguido. `app/agent/agent.py` arma el agente con `f"openai:{settings.openai_model}"`, así que cualquier modelo válido de OpenAI funciona sin tocar código. Confirmá el nombre exacto en `platform.openai.com/docs/models` antes de pegarlo.

## ¿Qué hago si Meta rechaza mi plantilla?

Fijate el motivo específico que te da el dashboard — la mayoría de los rechazos son por detalles de formato (mayúsculas, lenguaje promocional, variables mal escapadas), no por el contenido en sí. Ajustá y reenviá; no debería haber límite de reintentos, pero cada vuelta tarda, así que mandá las plantillas a revisión temprano (ver [05-anti-patrones.md](05-anti-patrones.md)). La documentación oficial de contenido de plantillas está entre los links de [02-configuracion-meta.md](02-configuracion-meta.md).
