from metro_collector.routing.travel_time import (
    TravelTimeEdge,
    estimate_travel_time,
    normalize_station_name,
)


def edge(
    from_stop: str,
    to_stop: str,
    from_name: str,
    to_name: str,
    line_code: str,
    seconds: int,
) -> TravelTimeEdge:
    return TravelTimeEdge(
        from_stop=from_stop,
        to_stop=to_stop,
        from_name=from_name,
        to_name=to_name,
        line_code=line_code,
        line_name=line_code,
        duration_sec=seconds,
    )


def test_normalizes_station_suffix_but_keeps_single_character_search() -> None:
    assert normalize_station_name(" 삼성역 ") == "삼성"
    assert normalize_station_name("삼") == "삼"
    assert normalize_station_name("역") == "역"


def test_estimates_direct_travel_time_and_collapses_line_leg() -> None:
    result = estimate_travel_time(
        [
            edge("A", "B", "삼성", "선릉", "SEOUL_2", 120),
            edge("B", "C", "선릉", "역삼", "SEOUL_2", 130),
            edge("C", "D", "역삼", "강남", "SEOUL_2", 110),
        ],
        origin="삼성역",
        destination="강남역",
    )
    assert result is not None
    assert result.total_seconds == 360
    assert result.transfer_count == 0
    assert result.stations == ("삼성", "선릉", "역삼", "강남")
    assert result.legs[0].station_count == 3


def test_adds_transfer_penalty_and_counts_transfer() -> None:
    result = estimate_travel_time(
        [
            edge("A1", "B1", "가", "환승", "LINE_1", 100),
            edge("B2", "C2", "환승", "다", "LINE_2", 150),
        ],
        origin="가",
        destination="다",
        transfer_seconds=300,
    )
    assert result is not None
    assert result.total_seconds == 550
    assert result.transfer_count == 1
    assert [leg.line_code for leg in result.legs] == ["LINE_1", "LINE_2"]
