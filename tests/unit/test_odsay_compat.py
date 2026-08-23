from metro_collector.api.odsay_compat import (
    StationMetadata,
    build_odsay_path_response,
    build_odsay_point_response,
)
from metro_collector.routing.schedule_route import RideLeg, ScheduleJourney, TransferLeg


def test_maps_schedule_journey_to_odsay_v18_path_shape() -> None:
    first_ride = RideLeg(
        kind="RIDE",
        line_code="SEOUL_1",
        line_name="수도권 1호선",
        direction="UP",
        trip_code="T1",
        train_number="1001",
        destination="소요산",
        from_station="가",
        to_station="환승",
        departure_sec=100,
        arrival_sec=400,
        duration_seconds=300,
        station_count=2,
        stations=("가", "나", "환승"),
    )
    transfer = TransferLeg(
        kind="TRANSFER",
        station="환승",
        from_line_code="SEOUL_1",
        from_line_name="수도권 1호선",
        from_direction="UP",
        to_line_code="SHINBUNDANG",
        to_line_name="신분당선",
        to_direction="DOWN",
        arrival_sec=400,
        walking_seconds=180,
        buffer_seconds=30,
        ready_sec=610,
        departure_sec=700,
        waiting_seconds=90,
        estimated=False,
    )
    second_ride = RideLeg(
        kind="RIDE",
        line_code="SHINBUNDANG",
        line_name="신분당선",
        direction="DOWN",
        trip_code="T2",
        train_number=None,
        destination="광교",
        from_station="환승",
        to_station="다",
        departure_sec=700,
        arrival_sec=1000,
        duration_seconds=300,
        station_count=1,
        stations=("환승", "다"),
    )
    journey = ScheduleJourney(
        origin_station="가",
        destination_station="다",
        requested_departure_sec=40,
        departure_sec=100,
        arrival_sec=1000,
        total_seconds=960,
        initial_wait_seconds=60,
        in_vehicle_seconds=600,
        transfer_walk_seconds=180,
        transfer_buffer_seconds=30,
        transfer_wait_seconds=90,
        transfer_count=1,
        stations=("가", "나", "환승", "다"),
        legs=(first_ride, transfer, second_ride),
    )
    stations = {
        name: StationMetadata(
            source_id=f"id-{index}",
            canonical_code=f"S{index}",
            name=name,
            latitude=37.0 + index * 0.01,
            longitude=127.0 + index * 0.01,
        )
        for index, name in enumerate(journey.stations)
    }

    response = build_odsay_path_response(journey, stations, walking_mode="standard")

    result = response["result"]
    assert result["searchType"] == 0
    assert result["subwayCount"] == 1
    path = result["path"][0]
    assert path["pathType"] == 1
    assert path["info"]["totalTime"] == 16
    assert path["info"]["subwayTransitCount"] == 1
    assert path["info"]["subwayStationCount"] == 3
    assert path["info"]["payment"] is None
    assert [section["trafficType"] for section in path["subPath"]] == [3, 1, 3, 1, 3]
    assert path["subPath"][1]["lane"][0]["subwayCode"] == 1
    assert path["subPath"][3]["lane"][0]["subwayCode"] == 109
    assert path["subPath"][2]["sectionTime"] == 4
    assert path["subPath"][1]["passStopList"]["stations"][0]["stationName"] == "가"


def test_missing_coordinates_are_represented_without_fabricated_location() -> None:
    leg = RideLeg(
        kind="RIDE",
        line_code="UIJEONGBU_LRT",
        line_name="의정부경전철",
        direction="UP",
        trip_code="T1",
        train_number=None,
        destination="탑석",
        from_station="발곡",
        to_station="회룡",
        departure_sec=100,
        arrival_sec=200,
        duration_seconds=100,
        station_count=1,
        stations=("발곡", "회룡"),
    )
    journey = ScheduleJourney(
        origin_station="발곡",
        destination_station="회룡",
        requested_departure_sec=100,
        departure_sec=100,
        arrival_sec=200,
        total_seconds=100,
        initial_wait_seconds=0,
        in_vehicle_seconds=100,
        transfer_walk_seconds=0,
        transfer_buffer_seconds=0,
        transfer_wait_seconds=0,
        transfer_count=0,
        stations=("발곡", "회룡"),
        legs=(leg,),
    )

    response = build_odsay_path_response(journey, {}, walking_mode="standard")

    result = response["result"]
    assert result["pointDistance"] is None
    ride = result["path"][0]["subPath"][1]
    assert ride["startX"] is None
    assert ride["endY"] is None
    assert ride["lane"][0]["subwayCode"] == 110


def test_maps_nearby_station_rows_to_odsay_point_search_shape() -> None:
    response = build_odsay_point_response(
        [
            {
                "id": "station-one",
                "name_ko": "강남",
                "latitude": 37.4974,
                "longitude": 127.0279,
                "lines": [
                    {
                        "line_code": "SHINBUNDANG",
                        "line_name": "신분당선",
                        "station_code": "D007",
                    }
                ],
            }
        ]
    )

    station = response["result"]["station"][0]
    assert response["result"]["count"] == 1
    assert station["stationClass"] == 2
    assert station["stationName"] == "강남"
    assert station["type"] == 109
    assert station["x"] == 127.0279
    assert isinstance(station["stationID"], int)
