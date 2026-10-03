# Túnel para desarrollo local

Meta no se conecta a vos: te hace `POST` a tu webhook. Tu máquina está detrás de NAT, así que necesitás una URL pública con HTTPS válido apuntando a tu app local (por defecto en `:8000`, ver `app/main.py`).

**Usá siempre el número de prueba de Meta para esto, nunca tu número de producción** — ver [docs/07-entornos-test-vs-produccion.md](../docs/07-entornos-test-vs-produccion.md). El túnel en sí no es lo que pone en riesgo tu número (el porqué está más abajo), pero no hay ninguna razón para exponer el número real mientras estás iterando.

## Opción 1: Cloudflare Tunnel (recomendado)

Gratis, sin límite práctico de banda ni de sesión, URL estable, y sin la página de interstitial que ngrok agrega en su free tier (ver Opción 3).

**Para qué el dominio propio, concretamente**: `cloudflared tunnel route dns` crea un registro DNS que apunta tu subdominio al túnel — sin dominio propio en Cloudflare no hay dónde crear ese registro, y sin él la URL no puede ser permanente (te quedás con el `*.trycloudflare.com` que cambia en cada reinicio). Alcanza con un subdominio (`dev.tudominio.com`), no hace falta que sea tu dominio principal ni gastar en uno nuevo si ya tenés alguno — un dominio cuesta ~USD 10-15/año si necesitás comprar uno. Si no querés ni eso, la Opción 2 (Tailscale Funnel) te da una URL igual de permanente sin necesitar dominio.

```bash
cloudflared tunnel login
cloudflared tunnel create agente-whatsapp-dev
cloudflared tunnel route dns agente-whatsapp-dev dev.tudominio.com
cloudflared tunnel run agente-whatsapp-dev --url http://localhost:8000
```

Para una prueba suelta sin dominio propio ni túnel nombrado, `cloudflared tunnel --url http://localhost:8000` te da una URL `*.trycloudflare.com` temporal — sirve para probar una vez, no para un ciclo de desarrollo sostenido (cambia en cada reinicio).

## Opción 2: Tailscale Funnel (si no tenés dominio propio)

Gratis en cualquier plan de Tailscale (incluido el personal), te da un subdominio bajo `*.ts.net` sin necesitar dominio propio ni configurar DNS. Alternativa razonable si estás arrancando — aclaración honesta: no encontramos gente usándolo puntualmente para webhooks de Meta/WhatsApp, es una recomendación por mérito técnico propio (funciona bien para exponer cualquier webhook), no un patrón verificado específico de este caso.

```bash
tailscale funnel 8000
tailscale funnel status   # confirmar que quedó activo
```

Dos cosas a tener en cuenta:
- El subdominio depende del nombre de tu máquina en la tailnet — normalmente es estable, pero puede cambiar solo si el nombre autogenerado se modifica (por ejemplo, tras una actualización del SO). Fijalo a mano desde la consola de admin de Tailscale si querés garantizar que nunca cambie.
- Necesitás `tailscaled` corriendo todo el tiempo en la máquina para que el funnel funcione — si la laptop se suspende o el proceso se cae, el webhook deja de llegar (mismo caso que cualquier túnel corriendo local).

## Opción 3: ngrok — ya no es gratis para este caso

Desde febrero de 2026 el free tier de ngrok agrega una página de advertencia (interstitial) a todo el tráfico HTTP del plan gratuito, y Meta no puede saltearla porque no manda headers custom en sus requests — en la práctica, esto **rompe la entrega del webhook** en el plan free. La propia documentación de ngrok para WhatsApp confirma que esta integración requiere plan pago (Pay-as-you-go o superior) con dominio reservado.

Si ya tenés plan pago de ngrok, sigue funcionando bien:

```bash
ngrok http 8000 --domain=tu-dominio-reservado.ngrok-free.app
```

O desde Python, con el helper de PyWa (`pywa.utils.start_ngrok_tunnel`), que además registra y verifica el webhook en Meta al arrancar si le pasás `app_id` y `app_secret`.

## Sobre el miedo a que el túnel "banee tu número"

No hay casos documentados de ngrok, ni de túneles en general, baneando cuentas de WhatsApp Business — buscamos específicamente esto y no aparece. Lo que sí puede pasar, y se confunde fácil con un ban:

- **Error de configuración, no de cuenta**: Meta a veces rechaza URLs `*.ngrok-free.app` compartidas al registrar el webhook, con el mensaje "the url has been identified as malicious and/or abusive". Es un error al configurar *esa URL puntual* (porque los subdominios gratis de ngrok son compartidos y rotan de dueño), no una sanción sobre tu número o tu cuenta. Se resuelve con un dominio propio o reservado.
- **El riesgo real no es la herramienta, es no verificar la firma**: si tu webhook no valida `X-Hub-Signature-256` (este template sí lo hace, ver `app/webhook/signature.py`), cualquiera que encuentre tu URL de túnel puede mandarte eventos falsos y lograr que tu bot le responda cosas no solicitadas a números reales — *eso* sí puede generar reportes de spam y pegarle a tu quality rating. La firma verificada cierra ese vector, uses el túnel que uses.
- Las causas reales y documentadas de baneo son otras, y ninguna tiene que ver con el túnel: mandar plantillas a contactos sin opt-in, quality rating sostenido en rojo, usar apps modificadas o APIs no oficiales (ver [docs/05-anti-patrones.md](../docs/05-anti-patrones.md)), o problemas con la verificación del negocio.

Si en su momento te banearon un número usando ngrok, vale la pena revisar el motivo exacto que dio Meta al desactivarlo (si lo guardaste) — es mucho más probable que haya sido alguna de las causas de arriba que el túnel en sí.

## Verificación del webhook

En cualquier opción, la URL del túnel es lo que registrás como `callback_url` en Meta ([docs/02-configuracion-meta.md](../docs/02-configuracion-meta.md)). El `GET /webhook` que responde a esa verificación ya está en `app/webhook/router.py` — compara el `hub.verify_token` de la query contra `META_WEBHOOK_VERIFY_TOKEN` de tu `.env`.

## Checklist de seguridad mientras el túnel está activo

- [ ] Firma `X-Hub-Signature-256` verificada (ya viene así en este template)
- [ ] Túnel restringido al path `/webhook` si la herramienta lo permite (Cloudflare: reglas de ingress; ngrok: Traffic Policy)
- [ ] Solo HTTPS
- [ ] `META_APP_SECRET` y `META_WEBHOOK_VERIFY_TOKEN` en `.env`, nunca commiteados ni logueados
- [ ] Apagás el túnel cuando no estás desarrollando activamente
- [ ] Estás en el número de prueba, no en el de producción — ver [docs/07-entornos-test-vs-produccion.md](../docs/07-entornos-test-vs-produccion.md)

**Nunca uses el túnel en producción.** Un webhook que cambia de URL en cada reinicio es exactamente lo que Meta penaliza — ver [docs/04-despliegue.md](../docs/04-despliegue.md).
