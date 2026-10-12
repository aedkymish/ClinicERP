"""Clinic-time helpers. Datetimes are stored as naive UTC and shown in the clinic time zone."""
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def to_utc(d: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, t, tzinfo=tz).astimezone(UTC).replace(tzinfo=None)


def to_local(dt: datetime | None, tz: ZoneInfo) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC).astimezone(tz)


def local_today(tz: ZoneInfo) -> date:
    return datetime.now(tz).date()


def day_bounds_utc(start: date, days: int, tz: ZoneInfo) -> tuple[datetime, datetime]:
    return to_utc(start, time(0), tz), to_utc(start + timedelta(days=days), time(0), tz)


def iso_utc(dt: datetime | None) -> str | None:
    return dt.replace(tzinfo=UTC).isoformat().replace("+00:00", "Z") if dt else None


def month_bounds(month: str) -> tuple[date, date]:
    y, m = (int(x) for x in month.split("-"))
    first = date(y, m, 1)
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return first, nxt - timedelta(days=1)
