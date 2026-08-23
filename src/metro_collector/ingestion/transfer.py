from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from psycopg.types.json import Jsonb

from metro_collector.db import Database, DbConnection
from metro_collector.domain.models import CollectedArtifact, NormalizedTransferConnection
from metro_collector.routing.travel_time import normalize_station_name


@dataclass(frozen=True, slots=True)
class TransferIngestionOutcome:
    parsed_count: int
    inserted_count: int
    unresolved_count: int


def _station_keys(value: str) -> tuple[str, ...]:
    normalized = normalize_station_name(value)
    without_parenthetical = re.sub(r"\([^)]*\)", "", normalized)
    if without_parenthetical == normalized:
        return (normalized,)
    return normalized, without_parenthetical


class TransferIngestionService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def ingest(
        self,
        *,
        source_code: str,
        source_url: str,
        artifact: CollectedArtifact,
        records: Iterable[NormalizedTransferConnection],
        effective_from: date,
    ) -> TransferIngestionOutcome:
        materialized = list(records)
        async with self._database.transaction() as connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (source_code,),
            )
            source_id = await self._source_id(connection, source_code)
            station_map = await self._station_map(connection)
            resolved: list[tuple[NormalizedTransferConnection, str, str, bool]] = []
            direct_keys: set[tuple[str, str]] = set()
            unresolved = 0
            for record in materialized:
                origins = self._resolve(station_map, record.from_line_code, record.station_name)
                destinations = self._resolve(station_map, record.to_line_code, record.station_name)
                if not origins or not destinations:
                    unresolved += 1
                    continue
                for origin_id in origins:
                    for destination_id in destinations:
                        if origin_id == destination_id:
                            continue
                        resolved.append((record, origin_id, destination_id, False))
                        direct_keys.add((origin_id, destination_id))
            for record, origin_id, destination_id, _ in tuple(resolved):
                if (destination_id, origin_id) not in direct_keys:
                    resolved.append((record, destination_id, origin_id, True))

            inserted = 0
            for record, origin_id, destination_id, derived_reverse in resolved:
                await self._upsert_transfer(
                    connection,
                    origin_id=origin_id,
                    destination_id=destination_id,
                    record=record,
                    source_code=source_code,
                    source_url=source_url,
                    effective_from=effective_from,
                    derived_reverse=derived_reverse,
                )
                inserted += 1
            await self._record_artifact(connection, source_id, artifact)
            return TransferIngestionOutcome(
                parsed_count=len(materialized),
                inserted_count=inserted,
                unresolved_count=unresolved,
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
    async def _station_map(connection: DbConnection) -> dict[tuple[str, str], set[str]]:
        cursor = await connection.execute(
            """
            SELECT ls.id::text AS line_station_id, line.code AS line_code, station.name_ko
            FROM line_station ls
            JOIN subway_line line ON line.id=ls.line_id
            JOIN station ON station.id=ls.station_id
            WHERE ls.active AND station.active
            """
        )
        result: dict[tuple[str, str], set[str]] = {}
        for row in await cursor.fetchall():
            for key in _station_keys(str(row["name_ko"])):
                result.setdefault((str(row["line_code"]), key), set()).add(
                    str(row["line_station_id"])
                )
        return result

    @staticmethod
    def _resolve(
        station_map: dict[tuple[str, str], set[str]],
        line_code: str,
        station_name: str,
    ) -> set[str]:
        for key in _station_keys(station_name):
            matches = station_map.get((line_code, key))
            if matches:
                return matches
        return set()

    @staticmethod
    async def _upsert_transfer(
        connection: DbConnection,
        *,
        origin_id: str,
        destination_id: str,
        record: NormalizedTransferConnection,
        source_code: str,
        source_url: str,
        effective_from: date,
        derived_reverse: bool,
    ) -> None:
        metadata: dict[str, Any] = {
            "source_code": source_code,
            "source_row_number": record.source_row_number,
            "station_name": record.station_name,
            "effective_from": str(effective_from),
        }
        if derived_reverse:
            metadata["derived_reverse"] = True
        cursor = await connection.execute(
            """
            UPDATE transfer_connection
            SET minimum_transfer_seconds=%(seconds)s,
                distance_m=%(distance_m)s,
                bidirectional=true,
                source_url=%(source_url)s,
                source_type='OFFICIAL',
                verified_at=now(),
                metadata=%(metadata)s
            WHERE from_line_station_id=%(origin_id)s::uuid
              AND to_line_station_id=%(destination_id)s::uuid
              AND from_direction IS NULL AND to_direction IS NULL
              AND valid_from IS NULL
            """,
            {
                "origin_id": origin_id,
                "destination_id": destination_id,
                "seconds": record.minimum_transfer_seconds,
                "distance_m": record.distance_m,
                "source_url": source_url,
                "metadata": Jsonb(metadata),
            },
        )
        if cursor.rowcount:
            return
        await connection.execute(
            """
            INSERT INTO transfer_connection (
                from_line_station_id, to_line_station_id,
                minimum_transfer_seconds, distance_m, bidirectional,
                source_url, source_type, verified_at, metadata
            ) VALUES (
                %(origin_id)s::uuid, %(destination_id)s::uuid,
                %(seconds)s, %(distance_m)s, true,
                %(source_url)s, 'OFFICIAL', now(), %(metadata)s
            )
            """,
            {
                "origin_id": origin_id,
                "destination_id": destination_id,
                "seconds": record.minimum_transfer_seconds,
                "distance_m": record.distance_m,
                "source_url": source_url,
                "metadata": Jsonb(metadata),
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
