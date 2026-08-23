from __future__ import annotations

import csv
import hashlib
import io
import re
from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import date
from pathlib import Path
from typing import TextIO

from metro_collector.collectors.base import TransitSourceCollector
from metro_collector.collectors.http import ArtifactDownloader, ConditionalRequest
from metro_collector.config import Settings
from metro_collector.domain.enums import (
    CoverageStatus,
    QualitySeverity,
    SourceAccessStatus,
    SourceKind,
)
from metro_collector.domain.models import (
    ActivationResult,
    CollectedArtifact,
    CollectionResult,
    NormalizedStopTime,
    QualityResult,
    SourceMetadata,
    ValidationResult,
)
from metro_collector.exceptions import CollectorConfigurationError, SourceFormatError

SOURCE_CODE = "SEOUL_OPEN_DATA_FULL_TIMETABLE"
DATASET_PAGE = "https://www.data.go.kr/data/15098251/fileData.do"

HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "line": ("호선", "노선", "노선명", "line", "line_name"),
    "station_code": ("역번호", "역코드", "역사코드", "전철역코드", "station_code"),
    "station_name": ("역명", "역사명", "전철역명", "station_name"),
    "service": ("주중주말", "요일", "요일구분", "운행요일", "day_type"),
    "direction": ("방향", "상하행", "상하행선", "direction"),
    "arrival": ("도착시간", "도착시각", "열차도착시간", "arrival_time"),
    "departure": ("출발시간", "출발시각", "열차출발시간", "departure_time"),
    "origin": ("기점", "출발역", "열차기점", "origin"),
    "destination": ("종점", "도착역", "열차종점", "destination"),
    "trip": ("열차코드", "열차번호", "열번", "trip_id", "train_no"),
    "express": ("급행여부", "열차종류", "급행", "express"),
    "sequence": ("정차순서", "역순번", "순번", "stop_sequence"),
}


def _normalize_header(value: str) -> str:
    return "".join(value.lstrip("\ufeff").strip().lower().replace("_", "").split())


NORMALIZED_ALIASES = {
    canonical: {_normalize_header(alias) for alias in aliases}
    for canonical, aliases in HEADER_ALIASES.items()
}

SERVICE_DAY_ROLLOVER_THRESHOLD_SECONDS = 12 * 60 * 60


def parse_service_seconds(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        raise SourceFormatError(f"Invalid service time: {value!r}")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except ValueError as error:
        raise SourceFormatError(f"Invalid service time: {value!r}") from error
    if hour < 0 or minute not in range(60) or second not in range(60):
        raise SourceFormatError(f"Invalid service time: {value!r}")
    return hour * 3600 + minute * 60 + second


def normalize_service_code(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "")
    if normalized in {"DAY", "평일", "WEEKDAY", "주중"}:
        return "WEEKDAY"
    if normalized in {"SAT", "토요일", "SATURDAY"}:
        return "SATURDAY"
    if normalized in {"END", "휴일", "일요일", "공휴일", "SUNDAY", "HOLIDAY"}:
        return "SUNDAY_HOLIDAY"
    return normalized


def normalize_direction(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "")
    mapping = {
        "UP": "UP",
        "상행": "UP",
        "IN": "INNER",
        "내선": "INNER",
        "DOWN": "DOWN",
        "하행": "DOWN",
        "OUT": "OUTER",
        "외선": "OUTER",
    }
    return mapping.get(normalized, normalized)


def normalize_line_code(value: str) -> str:
    normalized = value.strip().upper().replace(" ", "")
    match = re.fullmatch(r"0?([1-9])(?:호선|LINE)?", normalized)
    if match:
        return f"SEOUL_{match.group(1)}"
    return normalized


def _resolve_headers(fieldnames: Sequence[str]) -> dict[str, str]:
    normalized_source = {_normalize_header(name): name for name in fieldnames if name}
    resolved: dict[str, str] = {}
    for canonical, aliases in NORMALIZED_ALIASES.items():
        for alias in aliases:
            if alias in normalized_source:
                resolved[canonical] = normalized_source[alias]
                break
    required = {
        "line",
        "station_code",
        "station_name",
        "service",
        "direction",
        "arrival",
        "departure",
        "trip",
    }
    missing = sorted(required - resolved.keys())
    if missing:
        raise SourceFormatError(f"Required columns are missing: {', '.join(missing)}")
    return resolved


def _read_value(row: dict[str, str | None], headers: dict[str, str], key: str) -> str:
    source_header = headers.get(key)
    if source_header is None:
        return ""
    return (row.get(source_header) or "").strip()


def _trip_code(row: dict[str, str | None], headers: dict[str, str]) -> str:
    line_code = normalize_line_code(_read_value(row, headers, "line"))
    service_code = normalize_service_code(_read_value(row, headers, "service"))
    direction = normalize_direction(_read_value(row, headers, "direction"))
    trip_raw = _read_value(row, headers, "trip")
    return f"{line_code}:{service_code}:{direction}:{trip_raw}"


def _adjust_rollover_time(value: int | None, rolls_over: bool) -> int | None:
    if value is None:
        return None
    if rolls_over and value < SERVICE_DAY_ROLLOVER_THRESHOLD_SECONDS:
        return value + 24 * 60 * 60
    return value


def _parse_stop_times(
    row: dict[str, str | None], headers: dict[str, str]
) -> tuple[int | None, int | None]:
    arrival_sec = parse_service_seconds(_read_value(row, headers, "arrival"))
    departure_sec = parse_service_seconds(_read_value(row, headers, "departure"))
    # The current official file uses exactly 00:00:00 as a missing-value
    # sentinel on some Korail-operated rows; real post-midnight values use 24+.
    if arrival_sec == 0:
        arrival_sec = None
    if departure_sec == 0:
        departure_sec = None
    return arrival_sec, departure_sec


def parse_csv_stream(stream: TextIO) -> Iterator[NormalizedStopTime]:
    sample = stream.read(8192)
    stream.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(stream, dialect=dialect)
    if not reader.fieldnames:
        raise SourceFormatError("The timetable file has no CSV header")
    headers = _resolve_headers(reader.fieldnames)

    # The official Seoul file is station-major, not trip-major. Build a compact
    # time index first so inferred stop sequences describe the train journey
    # rather than the physical row order in the CSV.
    trip_events: defaultdict[str, list[tuple[int, int | None]]] = defaultdict(list)
    for row_number, row in enumerate(reader, start=2):
        arrival_sec, departure_sec = _parse_stop_times(row, headers)
        event_time = departure_sec if departure_sec is not None else arrival_sec
        trip_events[_trip_code(row, headers)].append((row_number, event_time))

    rollover_trips = {
        trip_code
        for trip_code, events in trip_events.items()
        if (times := [time for _, time in events if time is not None])
        and max(times) - min(times) > SERVICE_DAY_ROLLOVER_THRESHOLD_SECONDS
    }
    inferred_sequences: dict[int, int] = {}
    for trip_code, events in trip_events.items():
        ordered = sorted(
            events,
            key=lambda event: (
                _adjust_rollover_time(event[1], trip_code in rollover_trips)
                if event[1] is not None
                else float("inf"),
                event[0],
            ),
        )
        for sequence, (row_number, _) in enumerate(ordered, start=1):
            inferred_sequences[row_number] = sequence

    stream.seek(0)
    reader = csv.DictReader(stream, dialect=dialect)
    if not reader.fieldnames:
        raise SourceFormatError("The timetable file has no CSV header")
    headers = _resolve_headers(reader.fieldnames)

    for row_number, row in enumerate(reader, start=2):
        trip_raw = _read_value(row, headers, "trip")
        line_code = normalize_line_code(_read_value(row, headers, "line"))
        service_code = normalize_service_code(_read_value(row, headers, "service"))
        direction = normalize_direction(_read_value(row, headers, "direction"))
        trip_code = f"{line_code}:{service_code}:{direction}:{trip_raw}"
        sequence_raw = _read_value(row, headers, "sequence")
        if sequence_raw:
            try:
                stop_sequence = int(float(sequence_raw))
            except ValueError as error:
                raise SourceFormatError(
                    f"Invalid stop sequence at row {row_number}: {sequence_raw!r}"
                ) from error
        else:
            stop_sequence = inferred_sequences[row_number]

        arrival_sec, departure_sec = _parse_stop_times(row, headers)
        rolls_over = trip_code in rollover_trips

        express_raw = _read_value(row, headers, "express").upper()
        express_type = "EXPRESS" if express_raw in {"Y", "급행", "EXPRESS", "1"} else "LOCAL"
        yield NormalizedStopTime(
            line_code=line_code,
            station_code=_read_value(row, headers, "station_code"),
            station_name=_read_value(row, headers, "station_name"),
            service_code=service_code,
            direction=direction,
            trip_code=trip_code,
            train_number=trip_raw,
            stop_sequence=stop_sequence,
            arrival_sec=_adjust_rollover_time(arrival_sec, rolls_over),
            departure_sec=_adjust_rollover_time(departure_sec, rolls_over),
            origin_name=_read_value(row, headers, "origin") or None,
            destination_name=_read_value(row, headers, "destination") or None,
            express_type=express_type,
            source_row_number=row_number,
        )


def iter_csv_file(path: Path) -> Iterator[NormalizedStopTime]:
    with path.open("rb") as binary_stream:
        raw = binary_stream.read(4)
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "cp949"
    try:
        with path.open("r", encoding=encoding, newline="") as stream:
            yield from parse_csv_stream(stream)
    except UnicodeDecodeError:
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            yield from parse_csv_stream(stream)


class SeoulOpenDataCollector(TransitSourceCollector):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._downloader = ArtifactDownloader(
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            timezone=settings.timezone,
        )

    async def inspect(self) -> SourceMetadata:
        status = (
            SourceAccessStatus.ENABLED
            if self._settings.seoul_timetable_download_url
            else SourceAccessStatus.PENDING_REVIEW
        )
        return SourceMetadata(
            code=SOURCE_CODE,
            name="서울 도시철도 1~9호선 전체 열차운행시각표",
            kind=SourceKind.PUBLIC_DATASET,
            coverage=CoverageStatus.FULL_STATIC,
            access_status=status,
            base_url=DATASET_PAGE,
            stores_raw_artifact=True,
            notes="공공누리 제1유형; 다운로드 URL은 데이터셋 개정 시 재검증",
        )

    async def collect(self, previous: CollectedArtifact | None = None) -> CollectionResult | None:
        url = self._settings.seoul_timetable_download_url
        if not url:
            raise CollectorConfigurationError("SEOUL_TIMETABLE_DOWNLOAD_URL is not configured")
        filename = f"seoul-full-timetable-{date.today().isoformat()}.csv"
        artifact = await self._downloader.download(
            source_code=SOURCE_CODE,
            url=url,
            destination=self._settings.raw_data_dir / SOURCE_CODE / filename,
            conditional=ConditionalRequest(
                etag=previous.etag if previous else None,
                last_modified=previous.last_modified if previous else None,
            ),
        )
        if artifact is None:
            return None
        return CollectionResult(
            artifact=artifact,
            effective_from=self._settings.seoul_timetable_effective_from,
        )

    def iter_records(self, artifact: CollectedArtifact) -> Iterator[NormalizedStopTime]:
        yield from iter_csv_file(artifact.path)

    async def validate(self, artifact: CollectedArtifact) -> ValidationResult:
        count = 0
        errors: list[str] = []
        try:
            for record in self.iter_records(artifact):
                count += 1
                if not record.line_code or not record.station_code or not record.trip_code:
                    errors.append(f"row={record.source_row_number}: required identifier is empty")
                    if len(errors) >= 20:
                        break
        except SourceFormatError as error:
            errors.append(str(error))
        checks = (
            QualityResult(
                rule_code="SOURCE_FORMAT",
                severity=QualitySeverity.FATAL,
                passed=not errors,
                affected_count=len(errors),
                details={"sample_errors": errors},
            ),
            QualityResult(
                rule_code="NON_EMPTY",
                severity=QualitySeverity.FATAL,
                passed=count > 0,
                affected_count=0 if count > 0 else 1,
                details={"parsed_rows": count},
            ),
        )
        return ValidationResult(passed=all(check.passed for check in checks), checks=checks)

    async def activate(self, version_id: str) -> ActivationResult:
        return ActivationResult(
            activated=False,
            version_id=version_id,
            reason="Activation is transactionally performed by TimetableIngestionService",
        )


def checksum_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def parse_csv_text(content: str) -> list[NormalizedStopTime]:
    return list(parse_csv_stream(io.StringIO(content)))
