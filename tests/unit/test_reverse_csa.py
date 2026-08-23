from metro_collector.routing.csa import Connection, Footpath, ReverseConnectionScan


def test_finds_latest_direct_train_and_applies_walk_margins() -> None:
    router = ReverseConnectionScan([Connection("A", "D", 86_000, 87_000, "T1", "SEOUL_2")])
    journey = router.latest_departure(
        origin="A",
        destination="D",
        arrive_by_sec=87_600,
        access_walk_sec=600,
        egress_walk_sec=300,
        safety_margin_sec=120,
    )
    assert journey is not None
    assert journey.departure_sec == 85_400
    assert journey.arrival_sec == 87_300
    assert journey.transfer_count == 0


def test_finds_transfer_only_when_minimum_footpath_fits() -> None:
    connections = [
        Connection("A", "B", 100, 200, "T1", "SEOUL_2"),
        Connection("C", "D", 300, 400, "T2", "SUIN_BUNDANG"),
    ]
    router = ReverseConnectionScan(connections, [Footpath("B", "C", 80)])
    journey = router.latest_departure(origin="A", destination="D", arrive_by_sec=450)
    assert journey is not None
    assert [leg.kind for leg in journey.legs] == ["TRAIN", "WALK", "TRAIN"]
    assert journey.transfer_count == 1


def test_rejects_last_transfer_when_walk_time_does_not_fit() -> None:
    connections = [
        Connection("A", "B", 100, 250, "T1", "SEOUL_2"),
        Connection("C", "D", 300, 400, "T2", "SUIN_BUNDANG"),
    ]
    router = ReverseConnectionScan(connections, [Footpath("B", "C", 80)])
    assert router.latest_departure(origin="A", destination="D", arrive_by_sec=450) is None
