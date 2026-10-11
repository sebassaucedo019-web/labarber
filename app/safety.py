import re


_BANNED_WORDS = (
    (re.compile(r"\b(pendej(?:o|a|os|as))\b", re.IGNORECASE), "amigo"),
    (re.compile(r"\b(cabr(?:ón|ona|ones|onas)|cabron(?:es|as)?)\b", re.IGNORECASE), "amigo"),
    (re.compile(r"\b(pinche|pinches|culero|culera|culeros|culeras)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(puto|puta|putos|putas)\b", re.IGNORECASE), ""),
    (re.compile(r"\b(mierda|verga|chingar|chinga|chingado|chingada)\b", re.IGNORECASE), "problema"),
)


def sanitize_reply(text: str) -> str:
    """Remove common insults while preserving normal Mexican tone."""
    cleaned = text
    for pattern, replacement in _BANNED_WORDS:
        cleaned = pattern.sub(replacement, cleaned)
    return re.sub(r"[ \t]{2,}", " ", cleaned).strip()
