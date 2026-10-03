"""Descarga y transcripción de notas de voz de WhatsApp.

Flujo: Meta no manda el archivo en el webhook, manda un media_id. Hay que pedirle a la
Graph API la metadata de ese media_id (incluye una url temporal, ~5 min de vida) y después
bajar el archivo de esa url con el mismo token. Con los bytes en mano, se los pasás a
Whisper para transcribir.

Usa OPENAI_API_KEY (la misma que ya tenés para el agente) — no hace falta otra cuenta ni
otra dependencia. Si el volumen de audio crece y el costo por hora te empieza a importar,
Groq Whisper es ~3-9x más barato con la misma interfaz — ver README.md de esta carpeta.

No implementa respuesta en audio (TTS) — ver README.md de esta carpeta.
"""

import logging

import httpx
from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v25.0"  # confirmá la versión vigente en developers.facebook.com/docs/graph-api
GRAPH_BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"
WHISPER_MODEL = "whisper-1"


def download_audio(media_id: str) -> bytes | None:
    """Baja el audio de un mensaje de WhatsApp a partir de su media_id.
    Devuelve None si falla cualquier paso — nunca tira excepción hacia el worker."""
    media_url = _get_media_url(media_id)
    if media_url is None:
        return None
    return _fetch_media_bytes(media_url)


def _get_media_url(media_id: str) -> str | None:
    token = get_settings().whatsapp_access_token
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.get(f"{GRAPH_BASE_URL}/{media_id}", headers=headers, timeout=10)
        resp.raise_for_status()
        return resp.json()["url"]
    except (httpx.HTTPError, KeyError):
        logger.exception("no se pudo obtener metadata del media_id=%s", media_id)
        return None


def _fetch_media_bytes(media_url: str) -> bytes | None:
    token = get_settings().whatsapp_access_token
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = httpx.get(media_url, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.content
    except httpx.HTTPError:
        logger.exception("no se pudo descargar el archivo desde media_url")
        return None


def transcribe_audio(audio_bytes: bytes, filename: str = "audio.ogg") -> str | None:
    """Transcribe con la API de Whisper de OpenAI. Devuelve None si falla."""
    settings = get_settings()
    try:
        client = OpenAI(api_key=settings.openai_api_key)
        transcription = client.audio.transcriptions.create(
            file=(filename, audio_bytes),
            model=WHISPER_MODEL,
            language="es",
        )
        return transcription.text
    except Exception:
        logger.exception("fallo la transcripción con OpenAI Whisper")
        return None


def transcribe_whatsapp_audio(media_id: str) -> str | None:
    """Atajo: descarga + transcribe en un solo llamado. Es lo que llamás desde la tarea
    de cola (ver README.md — integración con app/queue/tasks.py)."""
    audio_bytes = download_audio(media_id)
    if audio_bytes is None:
        return None
    return transcribe_audio(audio_bytes)
