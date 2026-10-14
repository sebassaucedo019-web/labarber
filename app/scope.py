"""Filtro de alcance para evitar respuestas a mensajes ajenos al negocio."""

import re
import unicodedata


_BUSINESS_TERMS = (
    "barber", "barberia", "cita", "agendar", "agenda", "reservar", "reserva",
    "servicio", "servicios", "corte", "cortes", "barba", "precio", "precios",
    "cuanto cuesta", "cuanto sale", "cuanto cobran", "tarifa", "horario",
    "horarios", "disponibilidad", "disponible", "espacio", "barbero", "barberos",
    "obed", "jesus", "yadier", "cancelar", "cancelo", "reagendar", "reagendo",
    "cambiar cita", "siguiente cita", "turno", "hoy", "manana", "pasado manana",
    "dia", "hora", "silla", "atienden", "abren", "cierran", "ubicacion",
    "direccion", "donde estan", "llegar", "telefono", "whatsapp",
)
_DIRECT_BUSINESS_TERMS = tuple(
    term for term in _BUSINESS_TERMS
    if term not in {"hoy", "manana", "pasado manana", "dia", "hora", "silla"}
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
    if _OFF_TOPIC_RE.search(normalized) and not _has_business_term(
        normalized, _DIRECT_BUSINESS_TERMS
    ):
        return False
    return _has_business_term(normalized) or bool(
        re.search(r"\b(?:a las|a la|para las|para el)\s+\d{1,2}(?::\d{2})?\b", normalized)
    )


def _has_business_term(normalized: str, terms: tuple[str, ...] = _BUSINESS_TERMS) -> bool:
    """Match phrases or complete words so generic text does not pass by accident."""
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized)
        for term in terms
    )
