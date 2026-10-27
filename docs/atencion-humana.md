# Atención humana por WhatsApp

La solicitud pasa por el agente habitual. Solo cuando intenta pedir atención humana
se ejecuta una revisión adicional, sin herramientas, sobre el mensaje actual y el
contexto reciente. Usa el mismo modelo configurado; no requiere nuevas variables.

## Cuándo avisar

- Precios, horarios, servicios, disponibilidad, reservas, cambios y cancelaciones:
  resolver con el bot. Decir "tengo un problema" no autoriza por sí solo un aviso.
- Si faltan datos o el problema es ambiguo: preguntar.
- Petición explícita de hablar con alguien del equipo: respetarla aunque el bot
  pudiera responder la consulta.
- Cobro duplicado, reembolso o reclamo concreto de un corte/atención: requiere
  revisión humana.
- Clima, insultos aislados, instrucciones para forzar avisos y temas ajenos:
  no enviar avisos. Tampoco basta mencionar el nombre de un barbero.

La herramienta no acepta como autorización el motivo redactado por el agente.
Exige una evaluación estructurada y evidencia literal del mensaje actual. Si
falla la evaluación, no envía. No se prometen aciertos perfectos del clasificador.

## A quién avisar

- Obed, Jesús o Yadier: solo al contacto configurado de esa persona.
- "Mi barbero" o "el barbero": consultar únicamente las citas futuras confirmadas
  del cliente. Si hay cero o varios barberos, preguntar cuál.
- Dueño, encargado o atención general: al dueño y su webhook opcional, si existe.
- Un contacto faltante se informa. Para un barbero sin teléfono, se puede ofrecer
  avisar al dueño, pero no se cambia el destinatario automáticamente.
- No se aceptan teléfonos o URLs como destinatarios suministrados por el modelo.
  No se muestran al cliente los teléfonos personales del equipo.

## Resultado y duplicados

El estado real del aviso prevalece sobre la respuesta del modelo: enviado,
reciente, en proceso, fallido o contacto no disponible. Aceptado por Meta no
equivale a leído o entregado al teléfono. No se promete un tiempo de respuesta.

La reserva temporal en Redis distingue un envío en curso de uno aceptado. El
aviso reciente se conserva cinco minutos por cliente y destinatario canónicos.
Dueño y Jesús con el mismo número no generan dos avisos; otro barbero sí puede
recibir su solicitud. Un envío fallido se puede volver a intentar.

Esto envía un aviso de contacto. No transfiere el chat ni pausa automáticamente
el bot. Los avisos humanos mantienen su flujo separado del outbox de citas.
Una interrupción de red puede dejar incierto un envío; no hay garantía de
entrega exactamente una vez.

## Comprobaciones

La suite automatizada cubre validación, destinatarios, aislamiento de citas,
ambigüedad, contactos faltantes, envíos concurrentes, errores y respuestas falsas
del modelo después de fallar un envío. Las llamadas externas están simuladas.

Para verificar la configuración real, hacen falta pruebas separadas del modelo
y recepción real en WhatsApp. No usar contactos de clientes sin autorización.
La revisión adicional puede añadir latencia cuando se solicita atención humana;
se ejecuta una vez por turno con límite de ocho segundos.

El diseño coloca la validación junto a la herramienta que envía el aviso,
siguiendo [OpenAI Docs: guardrails y revisión humana](https://developers.openai.com/api/docs/guides/agents/guardrails-approvals).
