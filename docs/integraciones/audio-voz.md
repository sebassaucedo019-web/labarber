# Audio y notas de voz

Implementación de referencia: `examples/audio_transcripcion/`. Por default usa `OPENAI_API_KEY` (la misma que ya tenés para el agente) — no requiere cuenta ni dependencia nueva.

## Cómo se descarga un audio de WhatsApp

Meta no te manda el archivo directo en el webhook, te manda un `media_id`. El flujo es siempre en tres pasos:

1. **`media_id` → metadata**: un `GET` a la API de media de Meta con el `media_id` te devuelve una URL de descarga temporal y el `mime_type`.
2. **URL con expiración corta**: esa URL vive **~5 minutos**. Si no descargás el archivo en esa ventana, tenés que pedir el metadata de nuevo.
3. **Download**: un `GET` a esa URL (con tu `WHATSAPP_ACCESS_TOKEN` en el header) te da los bytes del archivo.

Por la ventana de expiración corta, este paso tiene que pasar dentro del worker (ver [01-arquitectura.md](../01-arquitectura.md)), no en el receptor — es exactamente el tipo de trabajo lento que el receptor no debe hacer.

## Transcripción: qué usar

- **OpenAI Whisper (default de este template)**: reusa `OPENAI_API_KEY`, cero fricción para arrancar. ~$0.36/hora de audio — para volumen bajo/medio son centavos, no vale la pena optimizar de entrada.
- **Groq Whisper**: ~3-9x más barato (~$0.04–0.11/hora), misma interfaz de API. Cambiá a esto cuando el volumen de audio sea real y el costo por hora empiece a importar — ver `examples/audio_transcripcion/README.md` para el swap exacto.
- **Deepgram**: si necesitás streaming en tiempo real o diarización (separar quién habla en un audio con varias personas). Para un bot de WhatsApp uno a uno, casi nunca hace falta.

## Responder con nota de voz (no como archivo adjunto)

Para que WhatsApp entregue tu respuesta como nota de voz nativa (con forma de onda, reproducible inline) el archivo tiene que ser **OGG con codec Opus y metadata correcta**. Si mandás cualquier otro formato — o un OGG mal formado — WhatsApp lo entrega como archivo adjunto normal, no como nota de voz. Si tu pipeline de TTS no genera OGG/Opus nativo, convertí antes de enviar (por ejemplo con ffmpeg, `-c:a libopus`).
