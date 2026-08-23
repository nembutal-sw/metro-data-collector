from metro_collector.collectors.kric_standard import (
    parse_station_list,
    parse_timed_stops,
    service_codes,
)


def test_parse_standard_plus_separated_stop_times() -> None:
    assert parse_timed_stops("D04-05:29+D05-05:30+D06-:") == {
        "D04": 5 * 3600 + 29 * 60,
        "D05": 5 * 3600 + 30 * 60,
        "D06": None,
    }


def test_parse_arex_alternating_code_and_time_format() -> None:
    assert parse_timed_stops("001+06:00+002+06:45+003+06:51") == {
        "001": 6 * 3600,
        "002": 6 * 3600 + 45 * 60,
        "003": 6 * 3600 + 51 * 60,
    }


def test_parse_slash_separated_uijeongbu_format_and_station_names() -> None:
    assert parse_timed_stops("001-05:00/002-05:01/003-:") == {
        "001": 5 * 3600,
        "002": 5 * 3600 + 60,
        "003": None,
    }
    assert parse_station_list("001-탑석역+002-송산역+003-발곡역") == [
        ("001", "탑석"),
        ("002", "송산"),
        ("003", "발곡"),
    ]


def test_holiday_table_is_available_on_saturday_and_sunday() -> None:
    assert service_codes("평일") == ("WEEKDAY",)
    assert service_codes("휴일") == ("SATURDAY", "SUNDAY_HOLIDAY")
    assert service_codes("토요일+일요일+공휴일") == (
        "SATURDAY",
        "SUNDAY_HOLIDAY",
    )
