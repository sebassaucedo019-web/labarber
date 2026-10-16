"""Filtro de alcance para evitar respuestas a mensajes ajenos al negocio."""

import re
import unicodedata


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

_GREETING_RE = re.compile(r"^(hola|hey|buenas(?: tardes| dias| noches)?|que onda|buen dia)[!.? ]*$")
_FOLLOW_UP_RE = re.compile(
    r"^(si|sí|ok|okay|va|dale|confirmo|confirmar|agendala|agéndala|hazlo|listo)[!.? ]*$",
    re.IGNORECASE,
)
_TIME_REPLY_RE = re.compile(
    r"^(?:a\s+las\s+)?\d{1,2}(?::\d{2})?\s*"
    r"(?:a\.?\s*m\.?|p\.?\s*m\.?|[ap]\.?|de\s+la\s+(?:manana|tarde|noche))?[!.? ]*$",
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


def _normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text.lower())
    return "".join(char for char in normalized if not unicodedata.combining(char))


def is_business_message(text: str, *, has_business_context: bool = False) -> bool:
    """Return True only for greetings or messages plausibly about the barber shop."""
    normalized = _normalize(text).strip()
    if not normalized:
        return False
    if _GREETING_RE.fullmatch(normalized):
        return True
    if _FOLLOW_UP_RE.fullmatch(normalized):
        return True
    if has_business_context and (
        _TIME_REPLY_RE.fullmatch(normalized) or _DETAIL_REPLY_RE.fullmatch(normalized)
    ):
        return True
    if _OFF_TOPIC_RE.search(normalized) and not _has_business_term(normalized, _DIRECT_BUSINESS_TERMS):
        return False
    # Once the conversation is clearly about the barber shop, allow natural
    # follow-ups such as "y qué más?", "cómo le hago?" or "y luego?". The
    # explicit off-topic guard above still blocks math, school, weather, etc.
    if has_business_context:
        return True
    return _has_business_term(normalized) or bool(_BUSINESS_INTENT_RE.search(normalized)) or bool(
        re.search(r"\b(?:a las|a la|para las|para el)\s+\d{1,2}(?::\d{2})?\b", normalized)
    )


def _has_business_term(normalized: str, terms: tuple[str, ...] = _BUSINESS_TERMS) -> bool:
    """Match phrases or complete words so generic text does not pass by accident."""
    return any(
        re.search(rf"(?<!\w){re.escape(term)}(?!\w)", normalized)
        for term in terms
    )
