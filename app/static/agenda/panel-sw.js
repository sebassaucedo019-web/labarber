// No appointments, login responses or tokens are ever cached on this device.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('fetch', event => {
  if (event.request.mode === 'navigate' && new URL(event.request.url).pathname === '/panel') {
    event.respondWith(fetch(event.request).catch(() => new Response(
      '<!doctype html><html lang="es"><meta name="viewport" content="width=device-width"><title>WAIA sin conexión</title><h1>Sin conexión</h1><p>Conéctate a internet para consultar la agenda. No se guardan cambios sin conexión.</p><a href="/panel">Volver a intentar</a></html>',
      {headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'}}
    )));
  }
});
