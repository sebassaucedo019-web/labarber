import re


_BANNED_WORDS = (
    (re.compile(r"\b(pendej(?:o|a|os|as))\b", re.IGNORECASE), "amigo"),
    (re.compile(r"\b(cabr(?:ón|ona|ones|onas)|cabron(?:es|as)?)\b", re.IGNORECASE), "amigo"),
    (re.compile(r"\b(idiota(?:s)?|est(?:ú|u)pido(?:s)?|imb(?:é|e)cil(?:es)?)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(mam(?:ón|ona|ones|onas)|mamon(?:es|as)?)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(pinche|pinches|culero|culera|culeros|culeras)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(puto|puta|putos|putas)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(mierda|verga|chingar|chinga|chingado|chingada)\b", re.IGNORECASE), "problema"),
    (re.compile(r"\b(no\s+mames|a\s+la\s+verga|vete\s+al\s+diablo)\b", re.IGNORECASE), ""),
)


def sanitize_reply(text: str) -> str:
    """Remove common insults while preserving normal Mexican tone.

    This is a last-mile guard: the model prompt sets the tone, but every outbound
    reply passes through here before it reaches WhatsApp.
    """
    cleaned = text
    for pattern, replacement in _BANNED_WORDS:
        cleaned = pattern.sub(replacement, cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned or "Con gusto te ayudo con servicios y citas de BARBER CG 💈"
