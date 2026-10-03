# Brief: Chatbot de WhatsApp con IA (Meta Cloud API oficial)

> Plantilla reutilizable para arrancar un bot de WhatsApp con LLM.
> Última revisión: agosto 2026.

---

## Cómo usar este brief

Tres formas, según lo que necesites:

1. **Como prompt para un agente de código** (Claude Code, Cursor, Codex). Rellena el bloque de variables, borra las secciones que no apliquen y pásale el fichero entero. Está escrito para que un agente pueda ejecutarlo sin preguntarte veinte cosas.
2. **Como documento de arranque de equipo.** Las decisiones ya vienen tomadas con su porqué, así se evita el debate de tres días sobre Python vs Node.
3. **Como checklist de revisión.** La sección de anti-patrones y la de pre-lanzamiento son las que más valen si el proyecto ya existe.

Lo que **no** es: un tutorial. No explica cómo crear una app en Meta Business paso a paso; eso cambia cada pocos meses y la documentación oficial es la fuente correcta.

---

## Variables a rellenar

```yaml
proyecto:
  nombre:              # ej. bot-reservas-clinica
  proposito:           # una frase: qué resuelve el bot
  idioma_usuarios:     # es / en / multi

alcance:
  casos_uso:           # 3-5 máximo para v1
  fuera_de_alcance:    # explícito, es lo que evita el scope creep
  volumen_estimado:    # conversaciones/mes — determina hosting y coste

whatsapp:
  numero:              # NUEVO, sin cuenta de WhatsApp previa
  pais_usuarios:       # afecta directamente a la tarifa por mensaje
  necesita_iniciar_conversacion:  # sí/no → si sí, necesitas plantillas aprobadas

tecnico:
  lenguaje:            # python (recomendado) | node
  modelo_llm:
  herramientas:        # funciones que el agente podrá llamar
  sistemas_a_integrar: # CRM, calendario, base de datos de pedidos...
  escalado_humano:     # sí/no → si sí, necesitas inbox (ver Chatwoot)
```

---

## Decisiones ya tomadas (y por qué)

### Transporte: WhatsApp Cloud API, directo con Meta

La versión on-premise quedó descontinuada en octubre de 2025; Cloud API es la única vía para integraciones nuevas. Cualquier guía que hable de levantar contenedores propios de WhatsApp está obsoleta.

Directo con Meta en lugar de un BSP porque los BSP añaden un margen típico de $0.003–$0.010 por mensaje. Un BSP tiene sentido si necesitas bandeja de agentes, constructor visual y CRM ya hechos; si estás leyendo este brief, probablemente no.

**Punto intermedio válido:** 360dialog — API pura, cuota mensual fija, sin cobro por mensaje encima del de Meta.

### Lenguaje: Python

No por ideología, sino porque PyWa no tiene equivalente real en Node. Cubre envío, recepción de webhooks, verificación de firma, Flows y plantillas, y su CLI (`pywa new`, `pywa new examples`, `pywa dev`, `pywa run`) te da un proyecto funcionando en minutos. En TypeScript te toca pegar tú esa capa.

**Excepción legítima:** si el equipo vive en TypeScript a diario, usa Node con `whatsapp-api-js`. Perder una semana peleando con Python cuesta más de lo que PyWa ahorra.

> Ojo con el sesgo al buscar en Google: la abundancia de contenido de Node viene de la comunidad de Baileys / whatsapp-web.js, que es la ruta **no oficial**. Ver anti-patrones.

### Conversación: bucle de agente, no árbol de decisión

No modeles `estado_3 → si dice X → estado_7`. Historial + system prompt + herramientas, y el modelo lleva la conversación. Lo único que persistes es el hilo por `wa_id`.

```python
@wa.on_message(filters.text)
def handle(_: WhatsApp, msg: types.Message):
    history = store.load(msg.from_user.wa_id)
    reply = agent.run(history + [msg.text], tools=[buscar_pedido, agendar, escalar])
    store.save(msg.from_user.wa_id, reply.messages)
    msg.reply(reply.text)
```

Herramientas mínimas que casi todo bot necesita: consulta al sistema de negocio, acción transaccional, y **escalado a humano** (no opcional — un bot sin salida hacia una persona genera clientes furiosos).

### Captura de datos estructurados: WhatsApp Flows

Para formularios (reserva, alta, dirección de envío) no preguntes campo por campo con el LLM. Flows son pantallas nativas dentro de WhatsApp. Mejor UX **y** más barato: un Flow es un mensaje facturable en lugar de ocho idas y vueltas. PyWa te deja definirlos en Python y gestiona el cifrado.

---

## Arquitectura obligatoria

```
Meta ──POST──► Receptor ──► Cola ──► Worker ──► LLM + herramientas
                (< 1s)     (Redis)    │
                                      └──► Cloud API ──► usuario
```

**La separación receptor / worker no es opcional.** El receptor valida la firma, encola y devuelve 200 en menos de un segundo. El worker hace el trabajo lento. Si llamas al LLM dentro del handler del webhook, la primera respuesta lenta dispara los reintentos de Meta y el usuario recibe la misma respuesta tres veces.

Requisitos que el agente de código debe implementar sin que se lo pidas dos veces:

| Requisito | Por qué |
|---|---|
| Verificación de firma `X-Hub-Signature-256` | Sin esto tu webhook es un endpoint público que cualquiera puede inundar |
| Idempotencia por `message_id` | Meta reintenta; sin dedupe procesas el mismo mensaje varias veces |
| Debounce de 2–3 s por `wa_id` | La gente escribe tres mensajes cortos seguidos, no uno largo |
| Timeout + fallback en la llamada al LLM | Si el modelo tarda 40 s, responde algo antes de que el usuario se vaya |
| Endpoint `/health` | Para monitorización externa (ver pre-lanzamiento) |
| Rate limit por usuario | Un usuario en bucle no debe vaciarte el presupuesto de tokens |
| Logs con `wa_id` hasheado, no en claro | Es un dato personal |

**Estado:** Redis para el hilo activo y el debounce; Postgres para historial persistente y auditoría. No metas historial largo entero en cada prompt — resume o recorta por ventana.

---

## Desarrollo local

El bot no se conecta a Meta: Meta hace POST a tu bot. Necesitas URL pública con HTTPS válido, y tu portátil está detrás de NAT. Solución: túnel.

```bash
pip install pywa
pywa new examples 02-order-bot   # esqueleto funcional
pywa dev                         # servidor de desarrollo
```

PyWa incluye `utils.start_ngrok_tunnel(auth_token=..., domain=...)`, que levanta el túnel y devuelve el `callback_url`. Pasándole además `app_id` y `app_secret`, se encarga del registro y la verificación del webhook en Meta al arrancar.

**Reserva un dominio estático en ngrok** (el tier gratis incluye uno). Sin él, cada reinicio genera URL nueva y toca re-registrar el webhook a mano.

Alternativa preferible si tienes dominio propio: **Cloudflare Tunnel** — gratis, nombre permanente, sin límite de conexiones del tier gratuito de ngrok.

---

## Despliegue

Restricciones que impone el webhook: HTTPS público, respuesta rápida y **uptime constante**. Meta degrada la calidad de tu número si los webhooks fallan de forma sostenida, y esa degradación te limita el volumen de envío.

Esto descarta los free tiers que duermen: el de Render apaga el servicio tras 15 minutos de inactividad y la primera petición tarda cerca de un minuto. Fly.io ya no ofrece crédito gratuito a cuentas nuevas.

| Opción | Cuándo |
|---|---|
| **Railway** | Arranque rápido. Deploy desde Git, Redis y Postgres integrados, web + worker en un proyecto. Suele salir en $10–15/mes para carga de un solo desarrollador. |
| **VPS Hetzner + Coolify/Dokploy** | Coste mínimo y control total. CX22 (2 vCPU, 4 GB) ~$4/mes con 20 TB de tráfico. Datacenter europeo = buena latencia a Meta. |
| **Google Cloud Run** | Si ya estás en GCP. `min-instances=1` obligatorio. |
| **Servidor en casa + Cloudflare Tunnel** | Viable de verdad: túnel permanente, sin IP estática ni abrir puertos. El riesgo es tu luz y tu fibra. |

Recomendación: empezar en Railway, migrar a VPS cuando la factura pase de $40–50.

**Producción:** `pywa run` con `callback_url` fijo apuntando a tu dominio permanente. Nunca el helper de ngrok en producción — un webhook que cambia en cada reinicio es exactamente lo que Meta penaliza.

---

## Modelo de costes

Desde julio de 2025 se paga **por mensaje entregado**, no por conversación. Los mensajes entrantes del usuario siguen siendo gratis.

**Cambios que hay que tener en el radar:**

- **1 oct 2026:** la ventana de servicio deja de ser gratuita. Los mensajes de servicio y las plantillas de utilidad dentro de la ventana vuelven a facturarse. Las tarifas exactas se publican el 1 de septiembre de 2026.
- **1 ago 2026:** las respuestas de IA de Meta ("Meta Business Agent") se cobran por token.

**Consecuencia de diseño directa:** un bot que responde en cinco mensajitos cortos costará cinco veces más que uno que responde bien de una vez. Instruye al modelo explícitamente a consolidar la respuesta en un solo mensaje. Y usa Flows para lo estructurado.

Presupuesto = (mensajes salientes × tarifa del país) + (tokens × precio del modelo) + hosting.

---

## Anti-patrones: qué NO hacer

**1. Baileys, whatsapp-web.js u OpenWA.** Conectan por QR sin pagar por mensaje y por eso llenan los tutoriales. Meta reforzó mucho la detección automática, y desde el 15 de enero de 2026 sus términos prohíben explícitamente la distribución de chatbots de IA de terceros en WhatsApp. Las cuentas con APIs no oficiales suelen durar entre 2 y 8 semanas antes del baneo permanente. Para un experimento personal, vale. Para un negocio, es construir sobre arena.

**2. Llamar al LLM dentro del handler del webhook.** Ver arquitectura. Es el error #1.

**3. Usar tu número personal de WhatsApp.** El número debe estar libre de cuenta de WhatsApp previa. Migrar uno en uso es doloroso y a veces irreversible.

**4. Free tier que duerme.** Cold start de un minuto = webhooks fallidos = calidad degradada.

**5. Un árbol de decisión con LLM encima.** O usas el modelo para llevar la conversación, o usas un flujo determinista. Mezclarlos da lo peor de ambos: rígido e impredecible a la vez.

**6. Bot sin salida a humano.** Añade la herramienta de escalado desde el día uno, aunque el "humano" al principio sea un email a ti.

**7. Prometer privacidad que no puedes dar.** Todos los mensajes pasan por la infraestructura de Meta. Puedes self-hostear tu aplicación, tus datos y hasta el modelo (Ollama/vLLM), pero no WhatsApp. Si el requisito real es que los mensajes no toquen a un tercero, WhatsApp no es el canal.

**8. Dejar las plantillas para el final.** Su aprobación tarda y las rechazan por detalles. Si el bot inicia conversaciones, empieza a enviarlas a revisión en la primera semana.

---

## Checklist de pre-lanzamiento

- [ ] Cuenta de Meta Business **verificada** (tarda; empieza pronto)
- [ ] Número dedicado, sin WhatsApp previo, con display name aprobado
- [ ] Plantillas necesarias enviadas y aprobadas
- [ ] Token permanente de System User (no el token temporal de 24 h del dashboard)
- [ ] Webhook registrado contra dominio permanente, firma verificada
- [ ] Suscripción a los campos correctos (`messages`, y `message_template_status_update` si usas plantillas)
- [ ] Cola y worker separados, con dedupe e idempotencia probados
- [ ] Debounce verificado con tres mensajes seguidos
- [ ] Monitorización externa contra `/health` (Uptime Kuma, Better Stack) — enterarte tú antes que Meta
- [ ] Alertas de gasto: tokens del modelo y mensajes de Meta
- [ ] Prueba de escalado a humano de punta a punta
- [ ] Aviso de privacidad y mecanismo de opt-out (`STOP` / `BAJA`) funcionando
- [ ] Plan para el cambio de facturación del 1 de octubre de 2026

---

## Extras opcionales

- **Chatwoot** self-hosted: bandeja de agentes, historial y traspaso a humano conectado a tu Cloud API. La forma más rápida de tener inbox sin pagar un BSP.
- **n8n** self-hosted: pegamento para integraciones si el bot es más "conectar sistemas" que "conversar".
- **Modelo local** (Ollama, vLLM con Llama/Qwen/Mistral): tiene sentido con volumen alto. Necesitas ~24 GB de VRAM para algo conversacionalmente decente; compara el alquiler de GPU contra el gasto en tokens antes de decidir.

---

## Fuentes a verificar antes de ejecutar

Las tarifas, los plazos y las políticas de Meta cambian a menudo. Antes de usar este brief, confirma:

- Precios y fechas: documentación de precios de WhatsApp Business Platform
- Estado de PyWa: `pywa.readthedocs.io`
- Términos vigentes: WhatsApp Business Messaging Policy
