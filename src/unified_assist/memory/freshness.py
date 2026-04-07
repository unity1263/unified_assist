from __future__ import annotations

from datetime import datetime, timezone


def age_days(timestamp: datetime, now: datetime | None = None) -> int:
    current = now or datetime.now(timezone.utc)
    delta = current - timestamp
    return max(0, delta.days)


def freshness_text(timestamp: datetime, now: datetime | None = None) -> str:
    days = age_days(timestamp, now=now)
    if days == 0:
        return "today"
    if days == 1:
        return "yesterday"
    return f"{days} days old"


def freshness_note(timestamp: datetime, now: datetime | None = None) -> str:
    days = age_days(timestamp, now=now)
    if days <= 1:
        return ""
    return (
        f"This memory is {days} days old. "
        "Treat it as point-in-time context and verify it against current state before relying on it."
    )
