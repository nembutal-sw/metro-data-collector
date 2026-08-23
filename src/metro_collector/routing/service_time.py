from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def parse_service_time(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise ValueError(f"Expected HH:MM or HH:MM:SS, got {value!r}")
    hour, minute = int(parts[0]), int(parts[1])
    second = int(parts[2]) if len(parts) == 3 else 0
    if hour < 0 or minute not in range(60) or second not in range(60):
        raise ValueError(f"Invalid service time: {value!r}")
    return hour * 3600 + minute * 60 + second


def format_service_time(seconds: int, *, include_seconds: bool = False) -> str:
    if seconds < 0:
        raise ValueError("Service time cannot be negative")
    hour, remainder = divmod(seconds, 3600)
    minute, second = divmod(remainder, 60)
    if include_seconds:
        return f"{hour:02d}:{minute:02d}:{second:02d}"
    return f"{hour:02d}:{minute:02d}"


def to_datetime(service_date: date, service_seconds: int, timezone: ZoneInfo) -> datetime:
    if service_seconds < 0:
        raise ValueError("Service time cannot be negative")
    start = datetime.combine(service_date, time.min, tzinfo=timezone)
    return start + timedelta(seconds=service_seconds)
