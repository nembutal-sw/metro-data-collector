from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from metro_collector.domain.enums import QualitySeverity
from metro_collector.domain.models import NormalizedStopTime, QualityResult, ValidationResult


def validate_normalized_stop_times(
    records: Iterable[NormalizedStopTime],
    *,
    required_line_codes: set[str] | None = None,
) -> ValidationResult:
    trip_events: defaultdict[str, list[tuple[int, int | None]]] = defaultdict(list)
    trip_counts: defaultdict[str, int] = defaultdict(int)
    seen_lines: set[str] = set()
    sequence_errors = 0
    time_errors = 0
    arrival_departure_errors = 0
    required_value_errors = 0
    row_count = 0

    for record in records:
        row_count += 1
        seen_lines.add(record.line_code)
        trip_counts[record.trip_code] += 1
        if not record.line_code or not record.station_code or not record.trip_code:
            required_value_errors += 1

        event_time = (
            record.departure_sec if record.departure_sec is not None else record.arrival_sec
        )
        if (
            record.arrival_sec is not None
            and record.departure_sec is not None
            and record.arrival_sec > record.departure_sec
        ):
            arrival_departure_errors += 1
        trip_events[record.trip_code].append((record.stop_sequence, event_time))

    for events in trip_events.values():
        previous_sequence: int | None = None
        previous_time: int | None = None
        for sequence, event_time in sorted(events, key=lambda event: event[0]):
            if previous_sequence is not None and sequence <= previous_sequence:
                sequence_errors += 1
            previous_sequence = sequence
            if event_time is not None:
                if previous_time is not None and event_time < previous_time:
                    time_errors += 1
                previous_time = event_time

    singleton_trips = sum(1 for count in trip_counts.values() if count < 2)
    missing_lines = sorted((required_line_codes or set()) - seen_lines)
    checks = (
        QualityResult(
            rule_code="NON_EMPTY",
            severity=QualitySeverity.FATAL,
            passed=row_count > 0,
            affected_count=0 if row_count else 1,
            details={"row_count": row_count},
        ),
        QualityResult(
            rule_code="REQUIRED_IDENTIFIERS",
            severity=QualitySeverity.FATAL,
            passed=required_value_errors == 0,
            affected_count=required_value_errors,
        ),
        QualityResult(
            rule_code="STOP_SEQUENCE_MONOTONIC",
            severity=QualitySeverity.ERROR,
            passed=sequence_errors == 0,
            affected_count=sequence_errors,
        ),
        QualityResult(
            rule_code="TRIP_TIME_MONOTONIC",
            severity=QualitySeverity.ERROR,
            passed=time_errors == 0,
            affected_count=time_errors,
        ),
        QualityResult(
            rule_code="ARRIVAL_NOT_AFTER_DEPARTURE",
            severity=QualitySeverity.ERROR,
            passed=arrival_departure_errors == 0,
            affected_count=arrival_departure_errors,
        ),
        QualityResult(
            rule_code="TRIP_HAS_MULTIPLE_STOPS",
            severity=QualitySeverity.ERROR,
            passed=singleton_trips == 0,
            affected_count=singleton_trips,
        ),
        QualityResult(
            rule_code="REQUIRED_LINES_PRESENT",
            severity=QualitySeverity.FATAL,
            passed=not missing_lines,
            affected_count=len(missing_lines),
            details={"missing_lines": missing_lines},
        ),
    )
    blocking = {QualitySeverity.ERROR, QualitySeverity.FATAL}
    return ValidationResult(
        passed=all(check.passed or check.severity not in blocking for check in checks),
        checks=checks,
    )
