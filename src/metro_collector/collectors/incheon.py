from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import TextIO
from urllib.parse import quote

from metro_collector.collectors.base import TransitSourceCollector
from metro_collector.collectors.http import ArtifactDownloader
from metro_collector.collectors.seoul_open_data import parse_service_seconds
from metro_collector.config import Settings
from metro_collector.domain.enums import (
    CoverageStatus,
    SourceAccessStatus,
    SourceKind,
)
from metro_collector.domain.models import (
    ActivationResult,
    CollectedArtifact,
    CollectionResult,
    NormalizedStopTime,
    SourceMetadata,
    ValidationResult,
)
from metro_collector.exceptions import CollectorConfigurationError, SourceFormatError
from metro_collector.quality.validators import validate_normalized_stop_times


def _normalize_header(value: str) -> str:
    return "".join(value.lstrip("\ufeff").strip().lower().replace("_", "").split())


ORIGIN_HEADERS = {_normalize_header(value) for value in ("시발역", "출발역", "기점")}
DESTINATION_HEADERS = {_normalize_header(value) for value in ("종착역", "도착역", "종점")}
TRAIN_HEADERS = {
    _normalize_header(value) for value in ("열차번호", "열차운행순번", "운행순번", "순번", "열번")
}


def _open_csv(path: Path) -> TextIO:
    with path.open("rb") as binary_stream:
        sample = binary_stream.read(65_536)
    if sample.startswith(b"\xef\xbb\xbf"):
        encoding = "utf-8-sig"
    else:
        try:
            sample.decode("utf-8")
            encoding = "utf-8-sig"
        except UnicodeDecodeError:
            encoding = "cp949"
    return path.open("r", encoding=encoding, newline="")


def _resolve_required_header(fieldnames: list[str], candidates: set[str], label: str) -> str:
    for fieldname in fieldnames:
        if _normalize_header(fieldname) in candidates:
            return fieldname
    raise SourceFormatError(f"Incheon timetable is missing the {label} column")


def parse_wide_timetable(
    stream: TextIO,
    *,
    line_code: str,
    service_code: str,
    direction: str,
) -> Iterator[NormalizedStopTime]:
    sample = stream.read(8192)
    stream.seek(0)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(stream, dialect=dialect)
    if not reader.fieldnames:
        raise SourceFormatError("Incheon timetable file has no CSV header")
    fieldnames = [name for name in reader.fieldnames if name]
    origin_header = _resolve_required_header(fieldnames, ORIGIN_HEADERS, "origin")
    destination_header = _resolve_required_header(fieldnames, DESTINATION_HEADERS, "destination")
    train_header = _resolve_required_header(fieldnames, TRAIN_HEADERS, "train number")
    train_index = fieldnames.index(train_header)
    station_headers = [
        name
        for name in fieldnames[train_index + 1 :]
        if _normalize_header(name) not in {"비고", "remark", "remarks"}
    ]
    if not station_headers:
        raise SourceFormatError("Incheon timetable has no station time columns")

    for row_number, row in enumerate(reader, start=2):
        train_number = (row.get(train_header) or "").strip()
        if not train_number:
            continue
        origin_name = (row.get(origin_header) or "").strip() or None
        destination_name = (row.get(destination_header) or "").strip() or None
        trip_code = f"{line_code}:{service_code}:{direction}:{train_number}"
        day_offset = 0
        previous_service_seconds: int | None = None
        for column_sequence, station_header in enumerate(station_headers, start=1):
            raw_time = (row.get(station_header) or "").strip()
            if not raw_time or raw_time in {"-", "—"}:
                continue
            station_name = station_header.strip()
            if station_name.endswith("역"):
                station_name = station_name[:-1]
            service_seconds = parse_service_seconds(raw_time)
            assert service_seconds is not None
            adjusted_seconds = service_seconds + day_offset
            if (
                previous_service_seconds is not None
                and adjusted_seconds < previous_service_seconds
                and previous_service_seconds - adjusted_seconds > 12 * 60 * 60
            ):
                day_offset += 24 * 60 * 60
                adjusted_seconds = service_seconds + day_offset
            previous_service_seconds = adjusted_seconds
            yield NormalizedStopTime(
                line_code=line_code,
                station_code=f"{line_code}:{station_name}",
                station_name=station_name,
                service_code=service_code,
                direction=direction,
                trip_code=trip_code,
                train_number=train_number,
                stop_sequence=column_sequence,
                arrival_sec=adjusted_seconds,
                departure_sec=adjusted_seconds,
                origin_name=origin_name,
                destination_name=destination_name,
                source_row_number=row_number * 1000 + column_sequence,
            )


class IncheonTransitCollector(TransitSourceCollector):
    def __init__(self, settings: Settings, line_number: int) -> None:
        if line_number not in (1, 2):
            raise ValueError("Only Incheon lines 1 and 2 are supported")
        self._settings = settings
        self._line_number = line_number
        self._line_code = f"INCHEON_{line_number}"
        self._source_code = f"INCHEON_{line_number}_TIMETABLE"
        self._downloader = ArtifactDownloader(
            timeout_seconds=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
            timezone=settings.timezone,
        )

    def _variants(self) -> list[tuple[str, str, str, str | None]]:
        prefix = f"incheon_{self._line_number}"
        return [
            ("weekday-up", "WEEKDAY", "UP", getattr(self._settings, f"{prefix}_weekday_up_url")),
            (
                "weekday-down",
                "WEEKDAY",
                "DOWN",
                getattr(self._settings, f"{prefix}_weekday_down_url"),
            ),
            (
                "holiday-up",
                "SUNDAY_HOLIDAY",
                "UP",
                getattr(self._settings, f"{prefix}_holiday_up_url"),
            ),
            (
                "holiday-down",
                "SUNDAY_HOLIDAY",
                "DOWN",
                getattr(self._settings, f"{prefix}_holiday_down_url"),
            ),
        ]

    def _resolve_download_url(self, template: str) -> str:
        if "{serviceKey}" not in template:
            return template
        configured_key = self._settings.data_go_kr_service_key
        if configured_key is None or not configured_key.get_secret_value():
            raise CollectorConfigurationError(
                "DATA_GO_KR_SERVICE_KEY is required by the configured Incheon URL"
            )
        encoded_key = quote(configured_key.get_secret_value(), safe="%")
        return template.replace("{serviceKey}", encoded_key)

    async def inspect(self) -> SourceMetadata:
        configured = all(url for _, _, _, url in self._variants())
        return SourceMetadata(
            code=self._source_code,
            name=f"인천 {self._line_number}호선 방향·요일별 시간표",
            kind=SourceKind.PUBLIC_DATASET,
            coverage=CoverageStatus.FULL_STATIC,
            access_status=(
                SourceAccessStatus.ENABLED if configured else SourceAccessStatus.PENDING_REVIEW
            ),
            base_url=(
                f"https://www.ictr.or.kr/main/railway/guidance/timetable{self._line_number}_se.jsp"
            ),
            stores_raw_artifact=True,
            notes="공공데이터포털 이용 제한 없음; 네 방향·요일 파일을 한 버전으로 활성화",
        )

    async def collect(self, previous: CollectedArtifact | None = None) -> CollectionResult | None:
        variants = self._variants()
        if not all(url for _, _, _, url in variants):
            raise CollectorConfigurationError(
                f"All four {self._line_code} timetable URLs must be configured"
            )
        retrieved_at = datetime.now(tz=self._settings.timezone)
        root = self._settings.raw_data_dir / self._source_code
        manifest_entries: list[dict[str, str]] = []
        for variant, service_code, direction, url in variants:
            assert url is not None
            artifact = await self._downloader.download(
                source_code=self._source_code,
                url=self._resolve_download_url(url),
                destination=root / f"{variant}.csv",
                recorded_url=url,
            )
            if artifact is None:
                raise RuntimeError("Unconditional Incheon download unexpectedly returned unchanged")
            manifest_entries.append(
                {
                    "variant": variant,
                    "service_code": service_code,
                    "direction": direction,
                    "path": str(artifact.path),
                    "url": artifact.source_url,
                    "checksum": artifact.checksum,
                }
            )
        combined_checksum = hashlib.sha256(
            "".join(entry["checksum"] for entry in manifest_entries).encode()
        ).hexdigest()
        if previous and previous.checksum == combined_checksum:
            return None
        manifest_path = root / "manifest.json"
        manifest_path.write_text(
            json.dumps({"files": manifest_entries}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifact = CollectedArtifact(
            source_code=self._source_code,
            source_url=(
                f"https://www.ictr.or.kr/main/railway/guidance/timetable{self._line_number}_se.jsp"
            ),
            retrieved_at=retrieved_at,
            checksum=combined_checksum,
            content_type="application/json",
            path=manifest_path,
        )
        return CollectionResult(
            artifact=artifact,
            effective_from=self._settings.incheon_timetable_effective_from,
        )

    def iter_records(self, artifact: CollectedArtifact) -> Iterator[NormalizedStopTime]:
        manifest = json.loads(artifact.path.read_text(encoding="utf-8"))
        for entry in manifest["files"]:
            with _open_csv(Path(entry["path"])) as stream:
                yield from parse_wide_timetable(
                    stream,
                    line_code=self._line_code,
                    service_code=entry["service_code"],
                    direction=entry["direction"],
                )

    async def validate(self, artifact: CollectedArtifact) -> ValidationResult:
        return validate_normalized_stop_times(
            self.iter_records(artifact),
            required_line_codes={self._line_code},
        )

    async def activate(self, version_id: str) -> ActivationResult:
        return ActivationResult(
            activated=False,
            version_id=version_id,
            reason="Activation is transactionally performed by TimetableIngestionService",
        )


def parse_wide_csv_text(
    content: str,
    *,
    line_code: str,
    service_code: str,
    direction: str,
) -> list[NormalizedStopTime]:
    return list(
        parse_wide_timetable(
            io.StringIO(content),
            line_code=line_code,
            service_code=service_code,
            direction=direction,
        )
    )
