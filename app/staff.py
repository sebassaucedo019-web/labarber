"""Configured staff directory; adding a barber does not require code changes."""

import unicodedata
from datetime import datetime

from app.config import BarberConfig, get_settings
from app.identity import normalize_phone


def roster() -> list[BarberConfig]:
    s = get_settings()
    return s.barbers or [
        BarberConfig(name="Obed", phone=s.barber_obed_wa_id),
        BarberConfig(name="Jesús", phone=s.barber_jesus_wa_id),
        BarberConfig(name="Yadier", phone=s.barber_yadier_wa_id),
    ]


def names() -> list[str]:
    return [b.name for b in roster()]


def key(value: str) -> str | None:
    def norm(s):
        return "".join(
            c
            for c in unicodedata.normalize("NFD", s.strip().casefold())
            if not unicodedata.combining(c)
        )

    return next((b.name for b in roster() if norm(b.name) == norm(value)), None)


def recipient(name: str) -> str | None:
    return next((normalize_phone(b.phone) for b in roster() if b.name == name), None)


def scope(wa_id: str) -> str | None:
    caller = normalize_phone(wa_id)
    if not caller:
        return None
    if caller == normalize_phone(get_settings().owner_wa_id):
        return "all"
    return next((b.name for b in roster() if normalize_phone(b.phone) == caller), None)


def working_slot(barber: str, at: datetime, duration_minutes: int = 30) -> bool:
    member = next((b for b in roster() if b.name == barber), None)
    if (
        member is None
        or at.minute % 30
        or at.second
        or at.microsecond
        or duration_minutes < 30
        or duration_minutes > 720
        or duration_minutes % 30
    ):
        return False
    windows = [[540, 1200]] if member.hours is None else member.hours.get(str(at.weekday()), [])
    minute = at.hour * 60 + at.minute
    return any(start <= minute and minute + duration_minutes <= end for start, end in windows)
