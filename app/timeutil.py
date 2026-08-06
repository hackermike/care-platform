"""Timezone-aware time handling.

`docs/DECISIONS.md` lists timezone-aware datetimes as a foundation item: Breakout
Billing stores naive local times, which cannot survive a hosted platform serving
networks across states. Everything here is UTC; presentation converts.

**SQLite caveat.** The test suite runs on SQLite, which has no native timestamp
type and hands back *naive* datetimes even for `DateTime(timezone=True)` columns.
Postgres returns aware ones. Comparing the two raises TypeError, so every value
read back from the database goes through `as_utc()` before it is compared.
"""
from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """Normalise a database value to an aware UTC datetime.

    Naive values are assumed UTC — true here because everything is written as
    UTC; it would be a bug to feed this a naive local time from elsewhere.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def minutes_from_now(minutes: int) -> datetime:
    return utcnow() + timedelta(minutes=minutes)


def hours_from_now(hours: int) -> datetime:
    return utcnow() + timedelta(hours=hours)
