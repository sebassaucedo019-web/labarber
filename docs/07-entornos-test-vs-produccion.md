# Entornos: número de prueba vs número de producción

La forma de desarrollar sin arriesgar nada: dos números, dos configuraciones, que nunca se cruzan.

## Los dos números

| | Número de prueba | Número de producción |
|---|---|---|
| Lo da | Meta, gratis, al crear la app | Vos, dado de alta específicamente para esto — sin cuenta de WhatsApp previa (ver [05-anti-patrones.md](05-anti-patrones.md)) |
| Destinatarios | Hasta 5, verificados manualmente por OTP | Cualquiera |
| Webhook apunta a | Tu túnel de desarrollo ([scripts/dev_tunnel.md](../scripts/dev_tunnel.md)) | El dominio fijo de tu deploy ([04-despliegue.md](04-despliegue.md)) |
| Riesgo si algo sale mal | Ninguno real — no hay clientes ni quality rating en juego | Tu operación de verdad |
| Cuándo usarlo | Todo el desarrollo local, siempre | Solo cuando el bot ya está probado y vas a mandar tráfico real |

**Regla simple: si estás corriendo un túnel, estás en el número de prueba. Si el webhook apunta a tu dominio de producción, es el número de producción — nunca al revés.**

## Por qué separar esto (no es paranoia)

El webhook es **por App de Meta, no por número**: cada app tiene una sola URL de callback + verify token configurados a la vez (App Dashboard → WhatsApp → Configuration). Los números (WABA) se suscriben a una app para que sus eventos lleguen a esa URL. Si metés el número de prueba y el de producción en la **misma** app, comparten esa única URL — no podés tener "el de prueba va al túnel" y "el de producción va al deploy" a la vez dentro de una sola app.

**Por eso conviene una app separada para producción.** Es gratis e instantáneo crear una segunda app en developers.facebook.com. Cada app mantiene su propio webhook fijo — la de desarrollo apuntando siempre a tu túnel, la de producción apuntando siempre a tu deploy — y no tenés que estar cambiando la URL de un lado a otro cada vez que pasás de programar a operar de verdad.

Si en cambio mezclás los dos números en la misma app, es fácil terminar con el webhook apuntando por error a una URL de túnel que ya ni existe (o al revés) — el síntoma es "el bot dejó de contestar" sin ningún error visible, porque Meta simplemente no le pega a la URL correcta.

### ¿Hay que re-registrar el webhook cada vez que te sentás a trabajar?

No, si el túnel tiene una URL **persistente**. Con un túnel con nombre + ruta DNS fija (Cloudflare Tunnel, ver [scripts/dev_tunnel.md](../scripts/dev_tunnel.md)) registrás la URL en Meta una sola vez, y de ahí en más solo corrés `cloudflared tunnel run <nombre>` — levanta siempre la misma URL, no hace falta volver al dashboard. Lo que sí te obliga a re-registrar cada vez es usar una URL efímera (ngrok free sin dominio reservado, o el `*.trycloudflare.com` de una corrida suelta): esa cambia en cada reinicio, y ahí sí tenés que actualizar el callback en Meta a mano cada sesión.

Además, el número de prueba no tiene quality rating ni clientes reales: podés romper cosas, reiniciar el túnel veinte veces, mandar mensajes de test raros, y no hay ningún efecto sobre tu operación real. Guardá el número de producción para cuando ya validaste el flujo — ver también por qué el túnel en sí no es el riesgo en [scripts/dev_tunnel.md](../scripts/dev_tunnel.md).

## Flujo de trabajo recomendado

1. **Desarrollo**: número de prueba + túnel + `.env` local. Iterás acá todo lo que haga falta, todas las veces que haga falta.
2. **Antes de mostrar avances o testear con gente real** (todavía no es "producción"): seguís en el número de prueba, agregás a las personas necesarias como destinatarios verificados (hasta 5). Si necesitás probar con más de 5 personas reales, pasá a un número de producción dedicado pero en un entorno de staging (ver más abajo) — no lo mezcles con el número de prueba compartido.
3. **Deploy**: levantás `app` + `worker` en tu proveedor elegido ([04-despliegue.md](04-despliegue.md)), con un dominio fijo.
4. **Recién ahí** cambiás la configuración del webhook en Meta para el número de producción, apuntándolo al dominio fijo del deploy — nunca a un túnel.
5. Apagás el túnel. El número de prueba queda libre para seguir iterando la siguiente feature sin tocar producción.

## Separar credenciales

`WHATSAPP_PHONE_NUMBER_ID` y `WHATSAPP_ACCESS_TOKEN` son distintos para el número de prueba y el de producción — son altas separadas en Meta. Guardalos en archivos separados para no pisarte uno con otro sin querer:

```
.env               # tu entorno local activo (gitignored) — normalmente el número de prueba
.env.production     # credenciales del número de producción — solo se usan en el deploy
```

No necesitás `.env.production` en tu laptop. Cargalo como variables de entorno directo en tu proveedor de deploy (Railway, Coolify, etc.); si en algún momento tenés que tenerlo en un archivo local, `.gitignore` ya cubre cualquier `.env.*` (con la única excepción de `.env.example`, que sí se commitea a propósito), así que no corrés riesgo de subirlo por accidente.

## Si tu equipo necesita un staging persistente

Para un equipo (no una sola persona iterando sola), a veces conviene un tercer número: un deploy real con dominio fijo, sin túnel, pero con un número de prueba dedicado a staging — separado tanto del número de prueba individual de cada dev como del número de producción real. Es más setup, tiene sentido cuando ya son varios tocando el mismo bot. No hace falta para arrancar solo.
