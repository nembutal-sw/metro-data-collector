from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from metro_collector.domain.enums import (
    CoverageStatus,
    QualitySeverity,
    SourceAccessStatus,
    SourceKind,
)


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    code: str
    name: str
    kind: SourceKind
    coverage: CoverageStatus
    access_status: SourceAccessStatus
    base_url: str
    stores_raw_artifact: bool
    uses_private_api: bool = False
    notes: str | None = None


@dataclass(frozen=True, slots=True)
class CollectedArtifact:
    source_code: str
    source_url: str
    retrieved_at: datetime
    checksum: str
    content_type: str | None
    path: Path
    etag: str | None = None
    last_modified: str | None = None


@dataclass(frozen=True, slots=True)
class NormalizedStopTime:
    line_code: str
    station_code: str
    station_name: str
    service_code: str
    direction: str
    trip_code: str
    stop_sequence: int
    arrival_sec: int | None
    departure_sec: int | None
    origin_name: str | None
    destination_name: str | None
    train_number: str | None = None
    express_type: str = "LOCAL"
    source_row_number: int | None = None


@dataclass(frozen=True, slots=True)
class NormalizedTransferConnection:
    from_line_code: str
    station_name: str
    to_line_code: str
    minimum_transfer_seconds: int
    distance_m: int | None
    source_row_number: int | None = None


@dataclass(frozen=True, slots=True)
class NormalizedStationCoordinate:
    line_code: str
    source_line_name: str
    source_station_code: str
    station_name: str
    station_name_en: str | None
    latitude: float
    longitude: float
    data_basis_date: date | None
    priority: int
    source_row_number: int | None = None


@dataclass(frozen=True, slots=True)
class QualityResult:
    rule_code: str
    severity: QualitySeverity
    passed: bool
    affected_count: int = 0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CollectionResult:
    artifact: CollectedArtifact
    effective_from: date
    effective_to: date | None = None
    record_count: int | None = None


@dataclass(frozen=True, slots=True)
class ValidationResult:
    passed: bool
    checks: tuple[QualityResult, ...]


@dataclass(frozen=True, slots=True)
class ActivationResult:
    activated: bool
    version_id: str | None
    reason: str | None = None
