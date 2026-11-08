"""UTC persistence, with explicit Chihuahua civil times at the booking boundary."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator

BUSINESS_TZ = ZoneInfo("America/Chihuahua")


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    candidates = {
        value.replace(tzinfo=BUSINESS_TZ, fold=fold).astimezone(UTC)
        for fold in (0, 1)
        if value.replace(tzinfo=BUSINESS_TZ, fold=fold)
        .astimezone(UTC)
        .astimezone(BUSINESS_TZ)
        .replace(tzinfo=None)
        == value
    }
    if len(candidates) != 1:
        raise ValueError("Hora local ambigua o inexistente en America/Chihuahua")
    return candidates.pop().replace(tzinfo=None)


class CalendarDateTime(TypeDecorator):
    """DB values are naive UTC; domain code receives naive Chihuahua wall time.

    Naive domain values always mean America/Chihuahua, never the server timezone.
    Timezone-aware inputs are accepted and converted using their actual offset.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return to_utc(value) if value is not None else None

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=UTC).astimezone(BUSINESS_TZ).replace(tzinfo=None)
