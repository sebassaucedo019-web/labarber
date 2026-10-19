"""Filtro de alcance para evitar respuestas a mensajes ajenos al negocio."""

import re
import unicodedata
from difflib import SequenceMatcher


_BUSINESS_TERMS = (
    "barber", "barberia", "cita", "agendar", "agenda", "reservar", "reserva",
    "servicio", "servicios", "corte", "cortes", "barba", "precio", "precios",
    "cuanto cuesta", "cuanto sale", "cuanto cobran", "tarifa", "horario",
    "horarios", "disponibilidad", "disponible", "espacio", "barbero", "barberos",
    "cabello", "pelo", "bigote", "ceja", "patilla", "perfilado", "rasurar",
    "degradado", "fade", "clasico", "normal", "juvenil", "nino", "niño", "lavado",
    "diseño", "diseno", "maquina", "tijera", "cortar", "cortarme", "arreglo",
    "efectivo", "tarjeta", "transferencia", "pago", "cuanto tardan", "duracion",
    "ubicacion", "direccion", "estacionamiento", "mapa", "como llego", "abierto",
    "cerrado", "trabajan", "ofrecen", "hacen", "atienden", "turno", "fila",
    "obed", "jesus", "yadier", "cancelar", "cancela", "cancelo", "cancelada",
    "canceladas", "cita", "citas", "reagendar", "reagendo",
    "cambiar cita", "siguiente cita", "turno", "hoy", "manana", "pasado manana",
    "dia", "hora", "silla", "atienden", "abren", "cierran", "ubicacion",
    "direccion", "donde estan", "llegar", "telefono", "whatsapp",
    "nombre", "la otra", "otra cita", "segunda cita", "viernes", "sabado", "domingo",
    "lunes", "martes", "miercoles", "jueves",
)
_DIRECT_BUSINESS_TERMS = tuple(
    term for term in _BUSINESS_TERMS
    if term not in {"hoy", "manana", "pasado manana", "dia", "hora", "silla"}
)

_GREETING_RE = re.compile(
    r"^(?:h+o+l+a+|o+l+a+|holi+|hey+|hello+|hi+|buenas(?:\s+(?:tardes|dias|noches))?|"
    r"buen dia|buenos dias|saludos|que onda|que tal|que rollo|que tranza|"
    r"como estas|como andas)[!.? ]*$"
)
_FUZZY_GREETING_PHRASES = (
    "buenas mananas",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "que onda",
    "que tal",
    "que rollo",
    "que tranza",
    "saludos",
)
_FOLLOW_UP_RE = re.compile(
    r"^(si|sí|ok|okay|va|dale|confirmo|confirmar|agendala|agéndala|hazlo|listo)[!.? ]*$",
    re.IGNORECASE,
)
_TIME_REPLY_RE = re.compile(
    r"^(?:(?:a\s+las\s+)?\d{1,2}(?::\d{2})?\s*"
    r"(?:a\.?\s*m\.?|p\.?\s*m\.?|[ap]\.?|de\s+la\s+(?:manana|tarde|noche))?"
    r"|a\.?\s*m\.?|p\.?\s*m\.?)\s*[!.? ]*$",
    re.IGNORECASE,
)
_DETAIL_REPLY_RE = re.compile(
    r"^(?:a\s+nombre\s+de|mi\s+nombre\s+es|soy|para)\b.+$",
    re.IGNORECASE,
)
_OFF_TOPIC_RE = re.compile(
    r"\b(?:tarea|matematicas?|ecuacion(?:es)?|suma|resta|multiplicacion|division|"
    r"escuela|clase|examen|program(?:a|acion|ar)|codigo|clima|futbol|noticias|"
    r"receta|cancion|lyrics|poema|traduce|ingles|resuelve|calcula|problema)\b"
)
_BUSINESS_INTENT_RE = re.compile(
    r"\b(?:quiero|necesito|busco|puedo|pueden|tienen|hay|me gustaria|me gustaria|"
    r"se puede|me puedo|voy|paso|caigo|mandame|pasa|dame|como|donde|cuando|"
    r"que|cual)\b.{0,80}\b(?:barberia|barber|corte|cortar|barba|cabello|pelo|"
    r"cita|agenda|precio|servicio|barbero|horario|hora|ubicacion|direccion|"
    r"fade|degradado|bigote|ceja|turno|silla|pago)\b"
)
_APPOINTMENT_ACTION_RE = re.compile(
    r"\b(?:cancel\w*|reagend\w*|reserv\w*|agend\w*)\b",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def is_greeting(text: str) -> bool:
    normalized = _normalize(text).strip()
    if _GREETING_RE.fullmatch(normalized):
        return True
    if len(normalized) < 5 or len(normalized) > 32:
        return False
    return any(
        SequenceMatcher(None, normalized, phrase).ratio() >= 0.86
        for phrase in _FUZZY_GREETING_PHRASES
    )


def is_business_message(text: str, *, has_business_context: bool = False) -> bool:
    """Return True only for greetings or messages plausibly about the barber shop."""
    normalized = _normalize(text).strip()
    if not normalized:
        return False
    if is_greeting(normalized):
        return True
    if _FOLLOW_UP_RE.fullmatch(normalized):
        return True
    if has_business_context and (
        _TIME_REPLY_RE.fullmatch(normalized) or _DETAIL_REPLY_RE.fullmatch(normalized)
    ):
        return True
    if _OFF_TOPIC_RE.search(normalized) and not _has_business_term(normalized, _DIRECT_BUSINESS_TERMS):
        return False
    if _APPOINTMENT_ACTION_RE.search(normalized):
        return True
    # Once the conversation is clearly about the barber shop, allow natural
    # follow-ups such as "y qué más?", "cómo le hago?" or "y luego?". The
    # explicit off-topic guard above still blocks math, school, weather, etc.
    if has_business_context:
        return True
    return _has_business_term(normalized) or bool(_BUSINESS_INTENT_RE.search(normalized)) or bool(
        re.search(r"\b(?:a las|a la|para las|para el)\s+\d{1,2}(?::\d{2})?\b", normalized)
    )


def is_contextual_follow_up(text: str) -> bool:
    """Allow only appointment details that make sense after a barber question."""
    normalized = _normalize(text).strip()
    return bool(
        _FOLLOW_UP_RE.fullmatch(normalized)
        or _TIME_REPLY_RE.fullmatch(normalized)
        or _DETAIL_REPLY_RE.fullmatch(normalized)
    )


def _has_business_term(normalized: str, terms: tuple[str, ...] = _BUSINESS_TERMS) -> bool:
    """Match phrases or complete words so generic text does not pass by accident."""
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized)
        for term in terms
    )
