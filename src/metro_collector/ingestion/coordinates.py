from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from metro_collector.db import Database, DbConnection
from metro_collector.domain.models import CollectedArtifact, NormalizedStationCoordinate
from metro_collector.exceptions import QualityGateError
from metro_collector.routing.travel_time import normalize_station_name

MINIMUM_MATCH_RATIO = 0.90
MAX_CANDIDATE_SPREAD_M = 1_500
MAX_EXISTING_DISPLACEMENT_M = 2_000

# Known public renames or shortened collector names that cannot be inferred by
# punctuation/parenthetical normalization alone.
STATION_NAME_ALIASES: dict[str, tuple[str, ...]] = {
    "신길온천": ("능길",),
    "능길": ("신길온천",),
}


@dataclass(frozen=True, slots=True)
class StationCoordinateTarget:
    station_id: str
    line_code: str
    name: str
    latitude: float | None
    longitude: float | None


@dataclass(frozen=True, slots=True)
class StationCoordinateMatch:
    target: StationCoordinateTarget
    coordinate: NormalizedStationCoordinate
    method: str
    accepted: bool
    rejection_reason: str | None = None


@dataclass(frozen=True, slots=True)
class StationCoordinateIngestionOutcome:
    parsed_count: int
    matched_count: int
    updated_count: int
    unresolved_count: int
    rejected_count: int


def _basic_name_keys(value: str) -> set[str]:
    normalized = normalize_station_name(value).replace("\uff08", "(").replace("\uff09", ")")
    variants = {normalized, re.sub(r"\([^)]*\)", "", normalized).strip()}
    return {
        re.sub(r"[\s·ㆍ._()-]", "", candidate).upper()
        for candidate in variants
        if candidate
    }


def _name_keys(value: str) -> set[str]:
    normalized = normalize_station_name(value)
    result = _basic_name_keys(normalized)
    for alias in STATION_NAME_ALIASES.get(normalized, ()):
        result.update(_basic_name_keys(alias))
    return result


def _distance_m(
    first_latitude: float,
    first_longitude: float,
    second_latitude: float,
    second_longitude: float,
) -> float:
    radius_m = 6_371_008.8
    first_lat = math.radians(first_latitude)
    second_lat = math.radians(second_latitude)
    delta_lat = second_lat - first_lat
    delta_lon = math.radians(second_longitude - first_longitude)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(first_lat) * math.cos(second_lat) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * radius_m * math.asin(math.sqrt(min(1.0, haversine)))


def _candidate_spread(records: Sequence[NormalizedStationCoordinate]) -> float:
    if len(records) < 2:
        return 0.0
    first = records[0]
    return max(
        _distance_m(first.latitude, first.longitude, row.latitude, row.longitude)
        for row in records[1:]
    )


def _best_candidate(
    records: Sequence[NormalizedStationCoordinate],
) -> NormalizedStationCoordinate:
    return max(
        records,
        key=lambda row: (
            row.priority,
            row.data_basis_date or date.min,
            -(row.source_row_number or 0),
        ),
    )


def match_station_coordinates(
    targets: Sequence[StationCoordinateTarget],
    records: Sequence[NormalizedStationCoordinate],
) -> tuple[list[StationCoordinateMatch], list[StationCoordinateTarget]]:
    indexed: list[tuple[NormalizedStationCoordinate, set[str]]] = [
        (record, _name_keys(record.station_name)) for record in records
    ]
    matches: list[StationCoordinateMatch] = []
    unresolved: list[StationCoordinateTarget] = []
    for target in targets:
        keys = _name_keys(target.name)
        candidates = [
            record
            for record, record_keys in indexed
            if record.line_code == target.line_code and keys & record_keys
        ]
        method = "LINE_AND_NAME"
        if not candidates:
            candidates = [record for record, record_keys in indexed if keys & record_keys]
            method = "SHARED_STATION_NAME"
        if not candidates:
            prefix_matches = [
                record
                for record, record_keys in indexed
                if record.line_code == target.line_code
                and any(
                    min(len(target_key), len(record_key)) >= 3
                    and (
                        target_key.startswith(record_key)
                        or record_key.startswith(target_key)
                    )
                    for target_key in keys
                    for record_key in record_keys
                )
            ]
            source_names = {record.station_name for record in prefix_matches}
            if len(source_names) == 1:
                candidates = prefix_matches
                method = "LINE_NAME_PREFIX"
        if not candidates or _candidate_spread(candidates) > MAX_CANDIDATE_SPREAD_M:
            unresolved.append(target)
            continue

        selected = _best_candidate(candidates)
        rejection_reason: str | None = None
        if target.latitude is not None and target.longitude is not None:
            displacement = _distance_m(
                target.latitude,
                target.longitude,
                selected.latitude,
                selected.longitude,
            )
            if displacement > MAX_EXISTING_DISPLACEMENT_M:
                rejection_reason = f"coordinate displacement {round(displacement)}m exceeds limit"
        matches.append(
            StationCoordinateMatch(
                target=target,
                coordinate=selected,
                method=method,
                accepted=rejection_reason is None,
                rejection_reason=rejection_reason,
            )
        )
    return matches, unresolved


class StationCoordinateIngestionService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def ingest(
        self,
        *,
        source_code: str,
        artifact: CollectedArtifact,
        records: Iterable[NormalizedStationCoordinate],
    ) -> StationCoordinateIngestionOutcome:
        materialized = list(records)
        async with self._database.transaction() as connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (source_code,),
            )
            source_id = await self._source_id(connection, source_code)
            targets = await self._targets(connection)
            matches, unresolved = match_station_coordinates(targets, materialized)
            accepted = [match for match in matches if match.accepted]
            rejected = [match for match in matches if not match.accepted]
            match_ratio = len(accepted) / len(targets) if targets else 0.0
            if match_ratio < MINIMUM_MATCH_RATIO:
                raise QualityGateError(
                    "Station coordinate match ratio is below the activation threshold: "
                    f"{len(accepted)}/{len(targets)} ({match_ratio:.1%})"
                )

            for match in accepted:
                await self._update_station(connection, source_id, match)
                await self._record_observation(
                    connection,
                    source_id=source_id,
                    artifact=artifact,
                    match=match,
                )
            for match in rejected:
                await self._record_observation(
                    connection,
                    source_id=source_id,
                    artifact=artifact,
                    match=match,
                )
            await self._record_artifact(connection, source_id, artifact)
            return StationCoordinateIngestionOutcome(
                parsed_count=len(materialized),
                matched_count=len(matches),
                updated_count=len(accepted),
                unresolved_count=len(unresolved),
                rejected_count=len(rejected),
            )

    @staticmethod
    async def _source_id(connection: DbConnection, source_code: str) -> str:
        cursor = await connection.execute(
            "SELECT id::text FROM source_registry WHERE code=%s AND access_status='ENABLED'",
            (source_code,),
        )
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"Enabled source is not registered: {source_code}")
        return str(row["id"])

    @staticmethod
    async def _targets(connection: DbConnection) -> list[StationCoordinateTarget]:
        cursor = await connection.execute(
            """
            SELECT station.id::text AS station_id, line.code AS line_code,
                   station.name_ko, station.latitude, station.longitude
            FROM station
            JOIN line_station ON line_station.station_id=station.id AND line_station.active
            JOIN subway_line line ON line.id=line_station.line_id AND line.active
            WHERE station.active
            ORDER BY line.code, station.name_ko, station.id
            """
        )
        return [
            StationCoordinateTarget(
                station_id=str(row["station_id"]),
                line_code=str(row["line_code"]),
                name=str(row["name_ko"]),
                latitude=float(row["latitude"]) if row["latitude"] is not None else None,
                longitude=float(row["longitude"]) if row["longitude"] is not None else None,
            )
            for row in await cursor.fetchall()
        ]

    @staticmethod
    async def _update_station(
        connection: DbConnection,
        source_id: str,
        match: StationCoordinateMatch,
    ) -> None:
        record = match.coordinate
        await connection.execute(
            """
            UPDATE station
            SET latitude=%(latitude)s,
                longitude=%(longitude)s,
                name_en=COALESCE(name_en, %(name_en)s),
                coordinate_source_id=%(source_id)s::uuid,
                coordinate_basis_date=%(basis_date)s,
                coordinate_updated_at=now()
            WHERE id=%(station_id)s::uuid
            """,
            {
                "station_id": match.target.station_id,
                "latitude": record.latitude,
                "longitude": record.longitude,
                "name_en": record.station_name_en,
                "source_id": source_id,
                "basis_date": record.data_basis_date,
            },
        )

    @staticmethod
    async def _record_observation(
        connection: DbConnection,
        *,
        source_id: str,
        artifact: CollectedArtifact,
        match: StationCoordinateMatch,
    ) -> None:
        record = match.coordinate
        await connection.execute(
            """
            INSERT INTO station_coordinate_observation (
                source_id, station_id, artifact_checksum, line_code,
                source_station_code, source_station_name, source_line_name,
                latitude, longitude, data_basis_date, source_row_number,
                match_method, accepted, rejection_reason
            ) VALUES (
                %(source_id)s::uuid, %(station_id)s::uuid, %(checksum)s,
                %(line_code)s, %(station_code)s, %(station_name)s,
                %(source_line_name)s, %(latitude)s, %(longitude)s,
                %(basis_date)s, %(row_number)s, %(match_method)s,
                %(accepted)s, %(rejection_reason)s
            )
            ON CONFLICT (
                source_id, artifact_checksum, line_code,
                source_station_code, station_id
            ) DO UPDATE SET
                latitude=EXCLUDED.latitude,
                longitude=EXCLUDED.longitude,
                data_basis_date=EXCLUDED.data_basis_date,
                source_row_number=EXCLUDED.source_row_number,
                match_method=EXCLUDED.match_method,
                accepted=EXCLUDED.accepted,
                rejection_reason=EXCLUDED.rejection_reason,
                observed_at=now()
            """,
            {
                "source_id": source_id,
                "station_id": match.target.station_id,
                "checksum": artifact.checksum,
                "line_code": match.target.line_code,
                "station_code": record.source_station_code,
                "station_name": record.station_name,
                "source_line_name": record.source_line_name,
                "latitude": record.latitude,
                "longitude": record.longitude,
                "basis_date": record.data_basis_date,
                "row_number": record.source_row_number,
                "match_method": match.method,
                "accepted": match.accepted,
                "rejection_reason": match.rejection_reason,
            },
        )

    @staticmethod
    async def _record_artifact(
        connection: DbConnection,
        source_id: str,
        artifact: CollectedArtifact,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO source_artifact (
                source_id, source_url, retrieved_at, etag, last_modified,
                content_type, content_length, checksum, storage_path
            ) VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, checksum) DO UPDATE SET
                source_url=EXCLUDED.source_url,
                retrieved_at=EXCLUDED.retrieved_at,
                etag=EXCLUDED.etag,
                last_modified=EXCLUDED.last_modified,
                content_type=EXCLUDED.content_type,
                content_length=EXCLUDED.content_length,
                storage_path=EXCLUDED.storage_path
            """,
            (
                source_id,
                artifact.source_url,
                artifact.retrieved_at,
                artifact.etag,
                artifact.last_modified,
                artifact.content_type,
                artifact.path.stat().st_size,
                artifact.checksum,
                str(artifact.path),
            ),
        )
