import re
from urllib.parse import urlsplit

OUT_OF_SCOPE_REPLY = (
    "Eso no lo puedo responder, yo solo te ayudo con la barbería. "
    "¿Quieres agendar una cita o saber precios?"
)

STAFF_HELP_REPLY = (
    "Este número está registrado como parte del equipo de BARBER CG. "
    "Puedo mostrarte la agenda, la siguiente cita, registrar una cita para un cliente "
    "con su nombre y teléfono, o ayudarte a cancelarla."
)
STAFF_OUT_OF_SCOPE_REPLY = (
    "Solo te ayudo con la operación de BARBER CG. "
    "¿Necesitas la agenda, registrar una cita para un cliente o cancelar una cita?"
)


_BANNED_WORDS = (
    (re.compile(r"\b(pendej(?:o|a|os|as))\b", re.IGNORECASE), "amigo"),
    (re.compile(r"\b(cabr(?:ón|ona|ones|onas)|cabron(?:es|as)?)\b", re.IGNORECASE), "amigo"),
    (
        re.compile(r"\b(idiota(?:s)?|est(?:ú|u)pido(?:s)?|imb(?:é|e)cil(?:es)?)\b", re.IGNORECASE),
        "",
    ),
    (re.compile(r"\b(mam(?:ón|ona|ones|onas)|mamon(?:es|as)?)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(pinche|pinches|culero|culera|culeros|culeras)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(puto|puta|putos|putas)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(mierda|verga|chingar|chinga|chingado|chingada)\b", re.IGNORECASE), "problema"),
    (re.compile(r"\b(no\s+mames|a\s+la\s+verga|vete\s+al\s+diablo)\b", re.IGNORECASE), ""),
)


def contains_banned_language(text: str) -> bool:
    """Detect offensive language so the agent can receive an extra guardrail."""
    return any(pattern.search(text) for pattern, _ in _BANNED_WORDS)


def retire_agenda_links(text: str) -> str:
    """Retire old web links in stored replies/history without discarding bookings."""

    def replace(match: re.Match[str]) -> str:
        url = match.group().rstrip(".,;:!?)]}")
        try:
            path = urlsplit(url).path.rstrip("/")
        except ValueError:
            return match.group()
        if path in {"/agenda", "/panel"}:
            return (
                "[Agenda web retirada; consulta las citas por WhatsApp]" + match.group()[len(url) :]
            )
        return match.group()

    return re.sub(r"https?://[^\s<>]+", replace, text, flags=re.IGNORECASE)


def sanitize_reply(text: str) -> str:
    """Remove common insults while preserving normal Mexican tone.

    This is a last-mile guard: the model prompt sets the tone, but every outbound
    reply passes through here before it reaches WhatsApp.
    """
    cleaned = retire_agenda_links(text)
    for pattern, replacement in _BANNED_WORDS:
        cleaned = pattern.sub(replacement, cleaned)
    # WhatsApp can display Markdown markers literally in plain-text replies.
    cleaned = cleaned.replace("*", "")
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned or "Con gusto te ayudo con servicios y citas de BARBER CG 💈"
