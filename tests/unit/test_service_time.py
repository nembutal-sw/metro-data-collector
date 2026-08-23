from datetime import date
from zoneinfo import ZoneInfo

import pytest

from metro_collector.routing.service_time import (
    format_service_time,
    parse_service_time,
    to_datetime,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("00:00", 0), ("23:59:59", 86_399), ("24:10", 87_000), ("25:05", 90_300)],
)
def test_parse_service_time_supports_after_midnight(value: str, expected: int) -> None:
    assert parse_service_time(value) == expected


def test_format_service_time_keeps_service_day_hour() -> None:
    assert format_service_time(90_300) == "25:05"


def test_to_datetime_moves_after_midnight_to_next_calendar_day() -> None:
    result = to_datetime(date(2026, 8, 23), 90_300, ZoneInfo("Asia/Seoul"))
    assert result.isoformat() == "2026-08-24T01:05:00+09:00"


@pytest.mark.parametrize("value", ["-1:00", "24:60", "abc", "12"])
def test_invalid_service_time_is_rejected(value: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        parse_service_time(value)
