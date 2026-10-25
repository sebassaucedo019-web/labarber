"""Canonical phone identities shared by permissions and outbound delivery."""


def normalize_phone(value: str | None) -> str | None:
    if not value or any(char not in "+0123456789 ()-." for char in value):
        return None
    digits = "".join(char for char in value if char in "0123456789")
    if len(digits) == 10:
        digits = "52" + digits
    elif len(digits) == 13 and digits.startswith("521"):
        digits = "52" + digits[3:]
    if not 11 <= len(digits) <= 15 or digits.startswith("0"):
        return None
    return digits


def phone_aliases(value: str) -> tuple[str, ...]:
    normalized = normalize_phone(value)
    if normalized is None:
        return (value,)
    if len(normalized) == 12 and normalized.startswith("52"):
        return normalized, "521" + normalized[2:], normalized[2:]
    return (normalized,)
