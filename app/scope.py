"""Filtro de alcance para evitar respuestas a mensajes ajenos al negocio."""

import re
import unicodedata


_BUSINESS_TERMS = (
    "barber", "barberia", "cita", "agendar", "agenda", "reservar", "reserva",
    "servicio", "corte", "barba", "precio", "precios", "tarifa", "horario",
    "disponibilidad", "disponible", "barbero", "obed", "jesus", "yadier",
    "cancelar", "cancelo", "reagendar", "cambiar cita", "siguiente cita",
    "turno", "hoy", "manana", "pasado manana", "dia", "hora", "silla",
)

_GREETING_RE = re.compile(r"^(hola|hey|buenas(?: tardes| dias| noches)?|que onda|buen dia)[!.? ]*$")
_OFF_TOPIC_RE = re.compile(
    r"\b(?:tarea|matematicas?|ecuacion(?:es)?|suma|resta|multiplicacion|division|"
    r"escuela|clase|examen|program(?:a|acion|ar)|codigo|clima|futbol|noticias|"
    r"receta|cancion|lyrics|poema|traduce|ingles)\b"
)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def is_business_message(text: str) -> bool:
    """Return True only for greetings or messages plausibly about the barber shop."""
    normalized = _normalize(text).strip()
    if not normalized:
        return False
    if _GREETING_RE.fullmatch(normalized):
        return True
    if _OFF_TOPIC_RE.search(normalized) and not any(
        term in normalized for term in _BUSINESS_TERMS
    ):
        return False
    return any(term in normalized for term in _BUSINESS_TERMS)
