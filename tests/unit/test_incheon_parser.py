from pydantic import SecretStr

from metro_collector.collectors.incheon import IncheonTransitCollector, parse_wide_csv_text
from metro_collector.config import Settings
from metro_collector.exceptions import CollectorConfigurationError


def test_parses_wide_train_rows_into_stop_times() -> None:
    content = """시발역,종착역,열차번호,검단호수공원,신검단중앙,아라,계양
검단호수공원,계양,1001,05:30:00,05:32:00,05:34:00,05:37:00
신검단중앙,계양,1003,,05:42:00,05:44:00,05:47:00
"""
    records = parse_wide_csv_text(
        content,
        line_code="INCHEON_1",
        service_code="WEEKDAY",
        direction="DOWN",
    )
    assert len(records) == 7
    assert records[0].trip_code == "INCHEON_1:WEEKDAY:DOWN:1001"
    assert records[0].station_name == "검단호수공원"
    assert records[0].departure_sec == 19_800
    assert records[-1].stop_sequence == 4
    assert records[-1].origin_name == "신검단중앙"


def test_skips_dash_and_blank_non_stops() -> None:
    content = """시발역,종착역,열차운행순번,운연,인천대공원,남동구청
운연,남동구청,1,24:10,-,24:15
"""
    records = parse_wide_csv_text(
        content,
        line_code="INCHEON_2",
        service_code="SUNDAY_HOLIDAY",
        direction="UP",
    )
    assert [record.station_name for record in records] == ["운연", "남동구청"]
    assert records[0].departure_sec == 87_000
    assert records[1].stop_sequence == 3


def test_accepts_line_two_sequence_header() -> None:
    content = """시발역,종착역,순번,운연,인천대공원
운연,인천대공원,1,05:30:00,05:33:00
"""
    records = parse_wide_csv_text(
        content,
        line_code="INCHEON_2",
        service_code="WEEKDAY",
        direction="UP",
    )
    assert len(records) == 2
    assert records[0].train_number == "1"


def test_normalizes_incheon_midnight_rollover() -> None:
    content = """시발역,종착역,순번,운연,인천대공원,남동구청
운연,남동구청,1,23:58:00,00:01:00,00:03:00
"""
    records = parse_wide_csv_text(
        content,
        line_code="INCHEON_2",
        service_code="WEEKDAY",
        direction="UP",
    )
    assert [record.departure_sec for record in records] == [86_280, 86_460, 86_580]


def test_service_key_placeholder_is_encoded_without_changing_percent_sequences() -> None:
    collector = IncheonTransitCollector(
        Settings(data_go_kr_service_key=SecretStr("abc+123%2F=")),
        1,
    )
    resolved = collector._resolve_download_url(
        "https://example.test/timetable?serviceKey={serviceKey}&type=csv"
    )
    assert resolved == "https://example.test/timetable?serviceKey=abc%2B123%2F%3D&type=csv"


def test_service_key_placeholder_requires_key() -> None:
    collector = IncheonTransitCollector(Settings(data_go_kr_service_key=None), 2)
    try:
        collector._resolve_download_url("https://example.test?serviceKey={serviceKey}")
    except CollectorConfigurationError:
        pass
    else:
        raise AssertionError("missing service key must reject a templated URL")
