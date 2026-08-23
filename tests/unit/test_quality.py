from pathlib import Path

from metro_collector.collectors.seoul_open_data import iter_csv_file
from metro_collector.domain.models import NormalizedStopTime
from metro_collector.quality.validators import validate_normalized_stop_times


def test_sample_passes_cross_source_quality_gates() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "seoul_timetable_sample.csv"
    result = validate_normalized_stop_times(
        iter_csv_file(fixture),
        required_line_codes={"SEOUL_2"},
    )
    assert result.passed
    assert all(check.passed for check in result.checks)


def test_quality_checks_trip_time_by_stop_sequence_not_input_order() -> None:
    common = {
        "line_code": "SEOUL_1",
        "station_name": "역",
        "service_code": "WEEKDAY",
        "direction": "UP",
        "trip_code": "SEOUL_1:WEEKDAY:UP:1",
        "train_number": "1",
        "arrival_sec": None,
        "origin_name": None,
        "destination_name": None,
        "express_type": "LOCAL",
    }
    records = [
        NormalizedStopTime(
            **common,
            station_code="B",
            stop_sequence=2,
            departure_sec=200,
        ),
        NormalizedStopTime(
            **common,
            station_code="A",
            stop_sequence=1,
            departure_sec=100,
        ),
    ]
    result = validate_normalized_stop_times(records)
    assert result.passed
