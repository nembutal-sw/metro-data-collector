from metro_collector.routing.schedule_route import (
    ForwardScheduleRouter,
    ScheduleConnection,
    TransferRule,
)


def connection(
    from_stop: str,
    to_stop: str,
    from_station: str,
    to_station: str,
    departure_sec: int,
    arrival_sec: int,
    trip_id: str,
    line_code: str,
    *,
    direction: str = "UP",
) -> ScheduleConnection:
    return ScheduleConnection(
        departure_stop=from_stop,
        arrival_stop=to_stop,
        departure_station=from_station,
        arrival_station=to_station,
        departure_sec=departure_sec,
        arrival_sec=arrival_sec,
        trip_id=trip_id,
        trip_code=trip_id,
        line_code=line_code,
        line_name=line_code,
        direction=direction,
        destination=to_station,
    )


def test_direct_route_uses_actual_departure_and_includes_dwell_time() -> None:
    router = ForwardScheduleRouter(
        [
            connection("A", "B", "가", "나", 100, 200, "T1", "LINE_1"),
            connection("B", "C", "나", "다", 220, 320, "T1", "LINE_1"),
        ]
    )

    journey = router.earliest_arrival(
        origin="가역",
        destination="다역",
        departure_sec=90,
    )

    assert journey is not None
    assert journey.departure_sec == 100
    assert journey.arrival_sec == 320
    assert journey.total_seconds == 230
    assert journey.initial_wait_seconds == 10
    assert journey.in_vehicle_seconds == 220
    assert journey.transfer_count == 0
    assert journey.legs[0].station_count == 2  # type: ignore[union-attr]


def test_transfer_walk_and_buffer_reject_too_early_train_and_count_transfer() -> None:
    connections = [
        connection("A1", "X1", "가", "환승", 100, 200, "T1", "LINE_1"),
        connection("X2", "D2", "환승", "다", 500, 590, "T2", "LINE_2", direction="DOWN"),
        connection("X2", "D2", "환승", "다", 600, 700, "T3", "LINE_2", direction="DOWN"),
    ]
    rules = [
        TransferRule(
            from_stop="X1",
            to_stop="X2",
            from_direction="UP",
            to_direction="DOWN",
            minimum_seconds=300,
            source_type="MEASURED",
        )
    ]

    journey = ForwardScheduleRouter(connections, rules).earliest_arrival(
        origin="가",
        destination="다",
        departure_sec=90,
        transfer_buffer_seconds=30,
    )

    assert journey is not None
    assert journey.departure_sec == 100
    assert journey.arrival_sec == 700
    assert journey.total_seconds == 610
    assert journey.transfer_count == 1
    assert journey.transfer_walk_seconds == 300
    assert journey.transfer_buffer_seconds == 30
    assert journey.transfer_wait_seconds == 70
    assert [leg.kind for leg in journey.legs] == ["RIDE", "TRANSFER", "RIDE"]


def test_slow_walking_mode_scales_station_specific_transfer_time() -> None:
    router = ForwardScheduleRouter(
        [
            connection("A1", "X1", "가", "환승", 100, 200, "T1", "LINE_1"),
            connection("X2", "D2", "환승", "다", 400, 500, "T2", "LINE_2"),
        ],
        [TransferRule("X1", "X2", 100, source_type="OFFICIAL")],
    )

    journey = router.earliest_arrival(
        origin="가",
        destination="다",
        departure_sec=90,
        walking_mode="slow",
        transfer_buffer_seconds=0,
    )

    assert journey is not None
    assert journey.transfer_walk_seconds == 150
    assert journey.transfer_wait_seconds == 50

