from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def utcnow() -> datetime:
    """Поточний час як aware-datetime в UTC."""
    return datetime.now(timezone.utc)


def ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite віддає datetime без tzinfo — доклеюємо UTC, щоб порівняння не падало."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def format_duration(seconds: float) -> str:
    """Людський запис тривалості: 90 -> "1 хв 30 с"."""
    total = int(max(0, round(seconds)))
    if total < 60:
        return f"{total} с"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} хв {secs} с" if secs else f"{minutes} хв"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} год {minutes} хв" if minutes else f"{hours} год"
