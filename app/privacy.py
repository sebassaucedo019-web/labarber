from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/privacy", response_class=HTMLResponse)
def privacy_policy() -> str:
    return """<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><title>Política de privacidad | BARBER CG</title></head>
<body style="font-family:Arial,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;line-height:1.6;color:#222">
<h1>Política de privacidad de BARBER CG</h1>
<p>Última actualización: 3 de octubre de 2026.</p>
<p>BARBER CG utiliza WhatsApp para atender consultas y gestionar citas de barbería.</p>
<h2>Información que recibimos</h2>
<p>Podemos recibir tu nombre, número de WhatsApp, mensajes y datos relacionados con tu cita, como servicio, fecha y hora.</p>
<h2>Cómo usamos la información</h2>
<p>Usamos estos datos únicamente para responder consultas, agendar o modificar citas, aplicar nuestras políticas de atención y dar seguimiento al servicio solicitado.</p>
<h2>Compartición y conservación</h2>
<p>No vendemos tus datos. La información se procesa mediante WhatsApp y los servicios técnicos necesarios para operar el bot. Conservamos los datos mientras sean necesarios para atender la relación con el cliente.</p>
<h2>Tus derechos</h2>
<p>Puedes solicitar acceso, corrección o eliminación de tus datos escribiendo al responsable de BARBER CG.</p>
<h2>Contacto</h2>
<p>Para cualquier solicitud de privacidad, responde en el chat de WhatsApp de BARBER CG y pide hablar con una persona.</p>
</body></html>"""
