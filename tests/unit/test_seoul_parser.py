from pathlib import Path

from metro_collector.collectors.seoul_open_data import iter_csv_file, parse_csv_text

FIXTURE = Path(__file__).parents[1] / "fixtures" / "seoul_timetable_sample.csv"


def test_parser_normalizes_line_service_direction_and_after_midnight() -> None:
    records = list(iter_csv_file(FIXTURE))
    assert len(records) == 5
    assert records[0].line_code == "SEOUL_2"
    assert records[0].service_code == "WEEKDAY"
    assert records[0].direction == "INNER"
    assert records[1].arrival_sec == 86_400
    assert records[-1].departure_sec == 90_210
    assert records[-1].express_type == "EXPRESS"


def test_parser_infers_stop_sequence_when_column_is_absent() -> None:
    content = """호선,역번호,역명,주중주말,방향,열차코드,도착시간,출발시간
1호선,100,가산,DAY,UP,K1,24:00,24:01
1호선,101,구로,DAY,UP,K1,24:05,24:06
"""
    records = parse_csv_text(content)
    assert [record.stop_sequence for record in records] == [1, 2]


def test_parser_infers_trip_order_from_time_in_station_major_file() -> None:
    content = """호선,역번호,역명,주중주말,방향,열차코드,도착시간,출발시간
1호선,101,구로,DAY,DOWN,K1,05:05,05:06
1호선,100,가산,DAY,DOWN,K1,05:00,05:01
"""
    records = parse_csv_text(content)
    assert [record.stop_sequence for record in records] == [2, 1]


def test_parser_normalizes_zero_hour_after_midnight() -> None:
    content = """호선,역번호,역명,주중주말,방향,열차코드,도착시간,출발시간
1호선,100,가산,DAY,UP,K1,23:58,23:59
1호선,101,구로,DAY,UP,K1,00:01,00:02
"""
    records = parse_csv_text(content)
    assert [record.stop_sequence for record in records] == [1, 2]
    assert records[1].arrival_sec == 86_460
    assert records[1].departure_sec == 86_520


def test_parser_treats_exact_zero_as_current_dataset_missing_sentinel() -> None:
    content = """호선,역번호,역명,주중주말,방향,열차코드,도착시간,출발시간
1호선,100,남영,DAY,DOWN,K1945,00:00:00,18:35:30
1호선,101,용산,DAY,DOWN,K1945,18:37:00,18:37:30
"""
    records = parse_csv_text(content)
    assert records[0].arrival_sec is None
    assert records[0].departure_sec == 66_930


def test_parser_accepts_current_public_data_portal_headers() -> None:
    content = """고유번호,호선,역사코드,역사명,주중주말,방향,급행여부,열차코드,열차도착시간,열차출발시간,출발역,도착역
400,1,0150,서울역,DAY,UP,0,K802,05:20:00,05:20:30,구로,동두천
"""
    records = parse_csv_text(content)
    assert records[0].station_code == "0150"
    assert records[0].station_name == "서울역"
    assert records[0].arrival_sec == 19_200
    assert records[0].departure_sec == 19_230
