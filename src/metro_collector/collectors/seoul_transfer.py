from __future__ import annotations

import csv
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

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
    NormalizedTransferConnection,
    QualityResult,
    SourceMetadata,
    ValidationResult,
)
from metro_collector.exceptions import CollectorConfigurationError, SourceFormatError

SOURCE_CODE = "SEOUL_TRANSFER_DISTANCE"
DATASET_PAGE = "https://www.data.go.kr/data/15044419/fileData.do"

LINE_CODES = {
    "경원선": "SEOUL_1",
    "국철": "SEOUL_1",
    "경의중앙선": "GYEONGUI_JUNGANG",
    "경춘선": "GYEONGCHUN",
    "공항철도": "AREX",
    "김포골드라인": "GIMPO_GOLD",
    "서해선": "SEOHAE",
    "수인분당선": "SUIN_BUNDANG",
    "신림선": "SILLIM",
    "신분당선": "SHINBUNDANG",
    "우이신설선": "UI_SINSEOL",
    "GTX-A": "GTX_A",
}


def normalize_transfer_line(value: str) -> str:
    normalized = "".join(value.strip().upper().split())
    match = re.fullmatch(r"0?([1-9])(?:호선)?", normalized)
    if match:
        return f"SEOUL_{match.group(1)}"
    try:
        return LINE_CODES[normalized]
    except KeyError as error:
        raise SourceFormatError(f"Unknown transfer line: {value!r}") from error


def parse_duration_seconds(value: str) -> int:
    parts = value.strip().split(":")
    if len(parts) != 2:
        raise SourceFormatError(f"Invalid transfer duration: {value!r}")
    try:
        minute, second = (int(part) for part in parts)
    except ValueError as error:
        raise SourceFormatError(f"Invalid transfer duration: {value!r}") from error
    if minute < 0 or second not in range(60) or minute + second == 0:
        raise SourceFormatError(f"Invalid transfer duration: {value!r}")
    return minute * 60 + second


def iter_transfer_csv(path: Path) -> Iterator[NormalizedTransferConnection]:
    with path.open("rb") as stream:
        raw = stream.read(4)
    encoding = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "cp949"
    try:
        yield from _iter_transfer_csv(path, encoding)
    except UnicodeDecodeError:
        yield from _iter_transfer_csv(path, "utf-8-sig")


def _iter_transfer_csv(path: Path, encoding: str) -> Iterator[NormalizedTransferConnection]:
    with path.open("r", encoding=encoding, newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"호선", "환승역명", "환승노선", "환승거리", "환승소요시간"}
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or ()))
            raise SourceFormatError(f"Required transfer columns are missing: {', '.join(missing)}")
        for row_number, row in enumerate(reader, start=2):
            try:
                distance_m = int(float((row["환승거리"] or "").strip()))
            except ValueError as error:
                raise SourceFormatError(
                    f"Invalid transfer distance at row {row_number}: {row['환승거리']!r}"
                ) from error
            if distance_m < 0:
                raise SourceFormatError(f"Negative transfer distance at row {row_number}")
            yield NormalizedTransferConnection(
                from_line_code=normalize_transfer_line(row["호선"] or ""),
                station_name=(row["환승역명"] or "").strip(),
                to_line_code=normalize_transfer_line(row["환승노선"] or ""),
                minimum_transfer_seconds=parse_duration_seconds(row["환승소요시간"] or ""),
                distance_m=distance_m,
                source_row_number=row_number,
            )


class SeoulTransferDistanceCollector(TransitSourceCollector):
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
            if self._settings.seoul_transfer_distance_download_url
            else SourceAccessStatus.PENDING_REVIEW
        )
        return SourceMetadata(
            code=SOURCE_CODE,
            name="서울교통공사 환승역 거리·소요시간",
            kind=SourceKind.DOWNLOAD_FILE,
            coverage=CoverageStatus.PARTIAL,
            access_status=status,
            base_url=DATASET_PAGE,
            stores_raw_artifact=True,
            notes="공식 공개 CSV; 일반인 보행속도 1.2m/s 기준",
        )

    async def collect(self, previous: CollectedArtifact | None = None) -> CollectionResult | None:
        url = self._settings.seoul_transfer_distance_download_url
        if not url:
            raise CollectorConfigurationError(
                "SEOUL_TRANSFER_DISTANCE_DOWNLOAD_URL is not configured"
            )
        today = datetime.now(tz=self._settings.timezone).date()
        artifact = await self._downloader.download(
            source_code=SOURCE_CODE,
            url=url,
            destination=(
                self._settings.raw_data_dir
                / SOURCE_CODE
                / f"seoul-transfer-distance-{today.isoformat()}.csv"
            ),
            conditional=ConditionalRequest(
                etag=previous.etag if previous else None,
                last_modified=previous.last_modified if previous else None,
            ),
        )
        # Re-apply the official transfer rows even when the file is unchanged.
        # A newly ingested line can make a previously unresolved transfer pair
        # resolvable without any change to this CSV.
        if artifact is None or (previous and previous.checksum == artifact.checksum):
            if previous is None:
                return None
            artifact = previous
        return CollectionResult(
            artifact=artifact,
            effective_from=self._settings.seoul_transfer_distance_effective_from,
            record_count=145,
        )

    def iter_transfers(self, artifact: CollectedArtifact) -> Iterator[NormalizedTransferConnection]:
        yield from iter_transfer_csv(artifact.path)

    def iter_records(self, artifact: CollectedArtifact) -> Iterator[NormalizedStopTime]:
        del artifact
        raise TypeError("Transfer-distance artifacts do not contain timetable stop records")
        yield

    async def validate(self, artifact: CollectedArtifact) -> ValidationResult:
        count = 0
        errors: list[str] = []
        try:
            for record in self.iter_transfers(artifact):
                count += 1
                if not record.station_name:
                    errors.append(f"row={record.source_row_number}: station name is empty")
        except SourceFormatError as error:
            errors.append(str(error))
        checks = (
            QualityResult(
                rule_code="SOURCE_FORMAT",
                severity=QualitySeverity.FATAL,
                passed=not errors,
                affected_count=len(errors),
                details={"sample_errors": errors[:20]},
            ),
            QualityResult(
                rule_code="EXPECTED_ROW_COUNT",
                severity=QualitySeverity.FATAL,
                passed=count >= 100,
                affected_count=0 if count >= 100 else 100 - count,
                details={"parsed_rows": count},
            ),
        )
        return ValidationResult(passed=all(check.passed for check in checks), checks=checks)

    async def activate(self, version_id: str) -> ActivationResult:
        return ActivationResult(
            activated=False,
            version_id=version_id,
            reason="Transfer rows are upserted by TransferIngestionService",
        )
