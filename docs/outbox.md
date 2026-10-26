# Avisos pendientes de citas

Desde esta version, `notification_outbox` guarda cada aviso en la misma
transaccion que confirma, cambia o cancela una cita. Si guardar un aviso falla,
se revierte la operacion completa. No se envia un aviso sobre una operacion
que todavia no se ha confirmado en la base.

## Despliegue

1. Respaldar PostgreSQL y desplegar web y worker con el mismo commit.
2. Mantener `python -m app.queue.worker` como comando del worker. No hacen falta
   nuevas variables ni otro servicio. El arranque crea la tabla adicional.
3. Confirmar en sus logs `outbox activo interval=5s`, ademas del worker RQ
   escuchando. `/health` y `/ready` de la web no verifican este despachador.
4. Retirar procesos de la version anterior; sus escrituras no usan el outbox.
5. Probar una cita identificada como prueba, con numeros autorizados y un cliente
   que no este registrado en `OWNER_WA_ID` o `BARBER_*_WA_ID`.

## Recuperacion

- Un hilo del worker revisa avisos pendientes cada cinco segundos. No depende
  de que Redis conserve un job de notificacion. Cada hilo usa sesiones SQL propias.
- `pending`: pendiente o esperando el siguiente intento.
- `sending`: reservado por un worker durante un maximo de 120 segundos.
  Si el proceso se interrumpe, otro intento lo recupera cuando vence el bloqueo.
- `sent`: Meta acepto la peticion y se guardo `accepted_at` (UTC).
  No equivale a un comprobante de entrega o lectura de WhatsApp.
- `failed`: se agotaron ocho intentos. La fila no se elimina.
- Las esperas son 15 s, 60 s, 5 min, 15 min y despues 1 h entre intentos.
  No se repiten operaciones de agenda para reintentar avisos.
- Los avisos de una misma cita y destinatario se procesan en orden. Un aviso
  agotado no bloquea para siempre los cambios posteriores.

El log usa el ID del aviso, no su contenido. Para inspeccion desde una conexion
autorizada de solo lectura a PostgreSQL:

```sql
SELECT status, count(*)
FROM notification_outbox
GROUP BY status;

SELECT id, appointment_id, status, attempts, available_at, last_error
FROM notification_outbox
WHERE status <> 'sent'
ORDER BY id
LIMIT 50;
```

Si hay `failed`, revisar primero token, destinatario y restricciones de Meta.
No volver a reservar o cancelar la cita para generar otro aviso. No reactivar
a ciegas avisos antiguos si hubo cambios posteriores en la cita. Revisar el estado
actual y resolver la comunicacion con el destinatario autorizado.

## Limites

Una caida despues de que Meta acepte el envio, pero antes de guardar `sent`,
puede causar un reenvio. El outbox evita perder el aviso entre guardar la cita
y programar su entrega, pero no garantiza entrega exactamente una vez.

No evita restricciones de la ventana de mensajeria, destinatarios de prueba,
plantillas o credenciales invalidas. No se agregaron recordatorios ni audios.
Los avisos humanos de `escalar_humano` mantienen su flujo separado.

Las pruebas automatizadas usan SQLite y envios simulados. Las pruebas en
PostgreSQL real y la recepcion real en los telefonos se verifican por separado.
