# Arquitectura: receptor → cola → worker

No es una preferencia de estilo, es un requisito impuesto por cómo funciona el webhook de Meta.

```
Meta ──POST──► Receptor ──► Cola ──► Worker ──► Agente (LLM + tools)
                (<1s)      (Redis)     │
                                       └──► Cloud API ──► usuario
```

En este repo: `app/webhook/router.py` es el receptor, `app/queue/client.py` + `app/queue/tasks.py` son la cola y el trabajo del worker (`app/queue/worker.py` lo corre), y `app/agent/agent.py` es el agente.

## Por qué la separación no es opcional

El receptor valida la firma, encola y devuelve 200 en menos de un segundo. El worker hace el trabajo lento: llamar al LLM, correr tools, escribir en Postgres. Si el LLM corriera dentro del handler del webhook, la primera respuesta lenta dispararía los reintentos de Meta y el usuario recibiría la misma respuesta duplicada — o triplicada.

Guardrails que implementa cada archivo:

| Requisito | Por qué | Dónde |
|---|---|---|
| Verificación de firma `X-Hub-Signature-256` | Sin esto el webhook es un endpoint público que cualquiera puede inundar | `app/webhook/signature.py` |
| Idempotencia por `message_id` | Meta reintenta; sin dedupe procesás el mismo mensaje varias veces | `app/queue/dedupe.py` |
| Debounce por `wa_id` | La gente manda tres mensajes cortos seguidos, no uno largo | `app/queue/debounce.py` (`DEBOUNCE_SECONDS` en `.env`, default 2.5s) |
| Timeout + fallback en la llamada al LLM | Si el modelo tarda, respondé algo antes de que el usuario se vaya | `app/queue/tasks.py` (`LLM_TIMEOUT_SECONDS`, `FALLBACK_REPLY`) |
| Endpoint `/health` | Para monitorización externa, ver [06-checklist-pre-lanzamiento.md](06-checklist-pre-lanzamiento.md) | `app/health.py` |
| Rate limit por usuario | Un usuario en bucle no te vacía el presupuesto de tokens | `app/observability.py` (`check_rate_limit`, `RATE_LIMIT_PER_MINUTE` en `.env`, default 20) |
| Logs con `wa_id` hasheado | Es un dato personal, no se loguea en claro | `app/observability.py` (`hash_wa_id`) |

Estado: Redis (`REDIS_URL`) para el hilo pendiente y el debounce; Postgres (`DATABASE_URL`) para historial persistente y auditoría (`app/store/models.py`).

## Decisión de este template: parseo manual del payload + PyWa solo para enviar

El receptor (`app/webhook/normalize.py`) parsea el JSON de Meta a mano, recorriendo `entry[].changes[].value.messages[]` directamente, en vez de usar los decoradores `@wa.on_message` de PyWa. PyWa aparece únicamente en `app/sender.py`, como cliente de envío (`get_client().send_message(...)`).

Trade-off, explícito:

- **Ventaja de parsear a mano:** ves la forma real del payload de Meta, que es justo lo que necesitás para debuggear cuando algo no matchea la documentación oficial. También hace trivial pasar el mensaje a la cola: RQ serializa argumentos simples (`wa_id: str`, `message_id: str`, `text: str`) entre el proceso del webhook y el proceso del worker; un objeto `Message` de PyWa no está pensado para cruzar ese límite de proceso.
- **Costo:** perdés el azúcar sintáctico de PyWa para recibir (routing por tipo de mensaje, filtros) y si Meta cambia la forma del payload, `normalize.py` es tuyo para mantener.

Para enviar no hay ese problema — `send_text` en `app/sender.py` no cruza procesos, así que usar el cliente de PyWa ahí es directo y no complica la serialización.

## La ventana de 24 horas

Meta solo deja mandar mensajes de texto libre dentro de las 24 horas desde el último mensaje del usuario. Fuera de esa ventana, sin una plantilla aprobada, el envío se rechaza. Por eso `app/sender.py` envuelve el envío en un `try/except` y **loguea el error en vez de asumir que el envío siempre funciona**:

```python
try:
    get_client().send_message(to=wa_id, text=text)
except Exception:
    logger.exception(
        "no se pudo enviar el mensaje wa_id_hash=%s — si el error es de ventana, "
        "revisá docs/01-arquitectura.md (regla de las 24h, necesitás una plantilla)",
        hash_wa_id(wa_id),
    )
```

Si tu bot necesita iniciar conversaciones (recordatorios, notificaciones), necesitás plantillas aprobadas — arrancá ese trámite temprano. Ver [05-anti-patrones.md](05-anti-patrones.md) y [02-configuracion-meta.md](02-configuracion-meta.md).
