from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Any

from psycopg.types.json import Jsonb

from metro_collector.db import Database, DbConnection
from metro_collector.domain.models import (
    CollectedArtifact,
    NormalizedStopTime,
    ValidationResult,
)


@dataclass(frozen=True, slots=True)
class IngestionOutcome:
    version_id: str
    activated: bool
    row_count: int
    unchanged: bool = False


class TimetableIngestionService:
    def __init__(self, database: Database) -> None:
        self._database = database

    async def ingest(
        self,
        *,
        source_code: str,
        artifact: CollectedArtifact,
        records: Iterable[NormalizedStopTime],
        effective_from: date,
        effective_to: date | None,
        source_validation: ValidationResult,
        activated_by: str,
    ) -> IngestionOutcome:
        async with self._database.transaction() as connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (source_code,),
            )
            source_id = await self._source_id(connection, source_code)
            existing = await self._existing_version(connection, source_id, artifact.checksum)
            if existing and existing["state"] != "FAILED":
                return IngestionOutcome(
                    version_id=existing["id"],
                    activated=existing["state"] == "ACTIVE",
                    row_count=existing["row_count"],
                    unchanged=True,
                )
            if existing:
                version_id = existing["id"]
                await self._reset_failed_version(
                    connection,
                    version_id=version_id,
                    artifact=artifact,
                    effective_from=effective_from,
                    effective_to=effective_to,
                )
            else:
                version_id = await self._create_version(
                    connection,
                    source_id=source_id,
                    artifact=artifact,
                    effective_from=effective_from,
                    effective_to=effective_to,
                )
            batch_id = await self._create_batch(connection, source_id, version_id)
            row_count = await self._copy_stage(connection, batch_id, records)
            await self._record_artifact(connection, source_id, version_id, artifact)
            await self._store_source_validation(connection, version_id, source_validation)

            database_checks = await self._database_quality_checks(connection, batch_id)
            all_checks_passed = source_validation.passed and all(
                check["passed"] for check in database_checks
            )
            await self._store_database_checks(connection, version_id, database_checks)

            if not all_checks_passed:
                await connection.execute(
                    "UPDATE timetable_version SET state='FAILED', row_count=%s WHERE id=%s",
                    (row_count, version_id),
                )
                await self._finish_batch(
                    connection,
                    batch_id,
                    row_count,
                    accepted=0,
                    rejected=row_count,
                )
                await connection.execute(
                    "DELETE FROM ingest_stop_time_stage WHERE batch_id=%s", (batch_id,)
                )
                return IngestionOutcome(
                    version_id=version_id,
                    activated=False,
                    row_count=row_count,
                )

            await self._materialize_reference_data(connection, batch_id, source_code)
            await self._materialize_default_transfers(connection)
            await self._materialize_timetable(connection, batch_id, version_id)
            await self._materialize_travel_time_edges(connection, version_id)
            await self._activate(connection, source_id, version_id, activated_by)
            await self._finish_batch(
                connection,
                batch_id,
                row_count,
                accepted=row_count,
                rejected=0,
            )
            await connection.execute(
                "DELETE FROM ingest_stop_time_stage WHERE batch_id=%s", (batch_id,)
            )
            return IngestionOutcome(
                version_id=version_id,
                activated=True,
                row_count=row_count,
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
    async def _existing_version(
        connection: DbConnection,
        source_id: str,
        checksum: str,
    ) -> dict[str, Any] | None:
        cursor = await connection.execute(
            """
            SELECT id::text, state::text, row_count
            FROM timetable_version WHERE source_id=%s::uuid AND checksum=%s
            """,
            (source_id, checksum),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    async def _create_version(
        connection: DbConnection,
        *,
        source_id: str,
        artifact: CollectedArtifact,
        effective_from: date,
        effective_to: date | None,
    ) -> str:
        version_code = f"{effective_from.isoformat()}-{artifact.checksum[:12]}"
        cursor = await connection.execute(
            """
            INSERT INTO timetable_version (
                source_id, version_code, state, effective_from, effective_to,
                collected_at, checksum
            ) VALUES (%s::uuid, %s, 'STAGED', %s, %s, %s, %s)
            RETURNING id::text
            """,
            (
                source_id,
                version_code,
                effective_from,
                effective_to,
                artifact.retrieved_at,
                artifact.checksum,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Failed to create a timetable version")
        return str(row["id"])

    @staticmethod
    async def _reset_failed_version(
        connection: DbConnection,
        *,
        version_id: str,
        artifact: CollectedArtifact,
        effective_from: date,
        effective_to: date | None,
    ) -> None:
        await connection.execute(
            "DELETE FROM data_quality_result WHERE timetable_version_id=%s::uuid",
            (version_id,),
        )
        await connection.execute(
            """
            UPDATE timetable_version
            SET state='STAGED', effective_from=%s, effective_to=%s,
                collected_at=%s, row_count=0
            WHERE id=%s::uuid AND state='FAILED'
            """,
            (effective_from, effective_to, artifact.retrieved_at, version_id),
        )

    @staticmethod
    async def _create_batch(connection: DbConnection, source_id: str, version_id: str) -> str:
        cursor = await connection.execute(
            """
            INSERT INTO ingest_batch (source_id, timetable_version_id)
            VALUES (%s::uuid, %s::uuid) RETURNING id::text
            """,
            (source_id, version_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise RuntimeError("Failed to create an ingestion batch")
        return str(row["id"])

    @staticmethod
    async def _copy_stage(
        connection: DbConnection,
        batch_id: str,
        records: Iterable[NormalizedStopTime],
    ) -> int:
        count = 0
        async with (
            connection.cursor() as cursor,
            cursor.copy(
                """
                COPY ingest_stop_time_stage (
                    batch_id, line_code, station_code, station_name, service_code,
                    direction, trip_code, train_number, stop_sequence, arrival_sec,
                    departure_sec, origin_name, destination_name, express_type,
                    source_row_number
                ) FROM STDIN
            """
            ) as copy,
        ):
            for record in records:
                await copy.write_row(
                    (
                        batch_id,
                        record.line_code,
                        record.station_code,
                        record.station_name,
                        record.service_code,
                        record.direction,
                        record.trip_code,
                        record.train_number,
                        record.stop_sequence,
                        record.arrival_sec,
                        record.departure_sec,
                        record.origin_name,
                        record.destination_name,
                        record.express_type,
                        record.source_row_number,
                    )
                )
                count += 1
        await connection.execute(
            "UPDATE ingest_batch SET parsed_rows=%s WHERE id=%s::uuid", (count, batch_id)
        )
        return count

    @staticmethod
    async def _record_artifact(
        connection: DbConnection,
        source_id: str,
        version_id: str,
        artifact: CollectedArtifact,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO source_artifact (
                source_id, timetable_version_id, source_url, retrieved_at, etag,
                last_modified, content_type, content_length, checksum, storage_path
            ) VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (source_id, checksum) DO UPDATE SET
                timetable_version_id=EXCLUDED.timetable_version_id,
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
                version_id,
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

    @staticmethod
    async def _store_source_validation(
        connection: DbConnection,
        version_id: str,
        validation: ValidationResult,
    ) -> None:
        for check in validation.checks:
            await connection.execute(
                """
                INSERT INTO data_quality_result (
                    timetable_version_id, rule_code, severity, passed, affected_count, details
                ) VALUES (%s::uuid, %s, %s, %s, %s, %s)
                ON CONFLICT (timetable_version_id, rule_code) DO UPDATE SET
                    severity=EXCLUDED.severity, passed=EXCLUDED.passed,
                    affected_count=EXCLUDED.affected_count, details=EXCLUDED.details,
                    checked_at=now()
                """,
                (
                    version_id,
                    f"SOURCE_{check.rule_code}",
                    check.severity.value,
                    check.passed,
                    check.affected_count,
                    Jsonb(check.details),
                ),
            )

    @staticmethod
    async def _database_quality_checks(
        connection: DbConnection,
        batch_id: str,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            WITH ordered AS (
                SELECT *,
                       lag(stop_sequence) OVER (
                           PARTITION BY trip_code ORDER BY stop_sequence, source_row_number
                       )
                           AS previous_sequence,
                       lag(COALESCE(departure_sec, arrival_sec)) OVER (
                           PARTITION BY trip_code ORDER BY stop_sequence, source_row_number
                       ) AS previous_time
                FROM ingest_stop_time_stage
                WHERE batch_id=%(batch_id)s::uuid
            ), stats AS (
                SELECT
                    count(*) AS row_count,
                    count(*) FILTER (
                        WHERE previous_sequence IS NOT NULL AND stop_sequence <= previous_sequence
                    ) AS sequence_errors,
                    count(*) FILTER (
                        WHERE previous_time IS NOT NULL
                          AND COALESCE(departure_sec, arrival_sec) < previous_time
                    ) AS time_errors,
                    count(*) FILTER (
                        WHERE arrival_sec IS NOT NULL AND departure_sec IS NOT NULL
                          AND arrival_sec > departure_sec
                    ) AS arrival_departure_errors,
                    count(*) FILTER (
                        WHERE line_code='' OR station_code='' OR station_name='' OR trip_code=''
                    ) AS identifier_errors
                FROM ordered
            ), missing_lines AS (
                SELECT count(*) AS count
                FROM (SELECT DISTINCT line_code FROM ordered) input
                LEFT JOIN subway_line line ON line.code=input.line_code
                WHERE line.id IS NULL
            )
            SELECT row_count, sequence_errors, time_errors, arrival_departure_errors,
                   identifier_errors,
                   missing_lines.count AS missing_line_errors
            FROM stats CROSS JOIN missing_lines
            """,
            {"batch_id": batch_id},
        )
        stats = await cursor.fetchone()
        if stats is None:
            raise RuntimeError("Database quality query returned no row")
        rules = [
            ("NON_EMPTY", stats["row_count"] > 0, 0 if stats["row_count"] else 1, "FATAL"),
            (
                "STOP_SEQUENCE_MONOTONIC",
                stats["sequence_errors"] == 0,
                stats["sequence_errors"],
                "ERROR",
            ),
            ("TRIP_TIME_MONOTONIC", stats["time_errors"] == 0, stats["time_errors"], "ERROR"),
            (
                "ARRIVAL_NOT_AFTER_DEPARTURE",
                stats["arrival_departure_errors"] == 0,
                stats["arrival_departure_errors"],
                "ERROR",
            ),
            (
                "REQUIRED_IDENTIFIERS",
                stats["identifier_errors"] == 0,
                stats["identifier_errors"],
                "FATAL",
            ),
            (
                "KNOWN_LINES",
                stats["missing_line_errors"] == 0,
                stats["missing_line_errors"],
                "FATAL",
            ),
        ]
        return [
            {"rule_code": code, "passed": passed, "affected_count": count, "severity": severity}
            for code, passed, count, severity in rules
        ]

    @staticmethod
    async def _store_database_checks(
        connection: DbConnection,
        version_id: str,
        checks: list[dict[str, Any]],
    ) -> None:
        for check in checks:
            await connection.execute(
                """
                INSERT INTO data_quality_result (
                    timetable_version_id, rule_code, severity, passed, affected_count
                ) VALUES (%s::uuid, %s, %s, %s, %s)
                """,
                (
                    version_id,
                    check["rule_code"],
                    check["severity"],
                    check["passed"],
                    check["affected_count"],
                ),
            )

    @staticmethod
    async def _materialize_reference_data(
        connection: DbConnection,
        batch_id: str,
        source_code: str,
    ) -> None:
        await connection.execute(
            """
            INSERT INTO station (canonical_code, name_ko)
            SELECT DISTINCT %(source_code)s || ':' || line_code || ':' || station_code, station_name
            FROM ingest_stop_time_stage
            WHERE batch_id=%(batch_id)s::uuid
            ON CONFLICT (canonical_code) DO UPDATE SET name_ko=EXCLUDED.name_ko
            """,
            {"source_code": source_code, "batch_id": batch_id},
        )
        await connection.execute(
            """
            WITH distinct_stations AS (
                SELECT DISTINCT line_code, station_code,
                       %(source_code)s || ':' || line_code || ':' || station_code AS canonical_code
                FROM ingest_stop_time_stage WHERE batch_id=%(batch_id)s::uuid
            ), numbered AS (
                SELECT *, dense_rank() OVER (PARTITION BY line_code ORDER BY station_code) AS sequence
                FROM distinct_stations
            )
            INSERT INTO line_station (line_id, station_id, station_code, sequence)
            SELECT l.id, s.id, n.station_code, n.sequence
            FROM numbered n
            JOIN subway_line l ON l.code=n.line_code
            JOIN station s ON s.canonical_code=n.canonical_code
            ON CONFLICT (line_id, station_code) DO UPDATE SET station_id=EXCLUDED.station_id, active=true
            """,
            {"source_code": source_code, "batch_id": batch_id},
        )

    @staticmethod
    async def _materialize_timetable(
        connection: DbConnection,
        batch_id: str,
        version_id: str,
    ) -> None:
        await connection.execute(
            """
            WITH trip_rows AS (
                SELECT stage.trip_code,
                       max(stage.train_number) AS train_number,
                       max(stage.direction) AS direction,
                       max(stage.express_type) AS express_type,
                       line.id AS line_id,
                       calendar.id AS service_id,
                       (array_agg(ls.id ORDER BY stage.stop_sequence))[1] AS origin_id,
                       (array_agg(ls.id ORDER BY stage.stop_sequence DESC))[1] AS destination_id
                FROM ingest_stop_time_stage stage
                JOIN subway_line line ON line.code=stage.line_code
                JOIN service_calendar calendar ON calendar.service_code=stage.service_code
                JOIN line_station ls ON ls.line_id=line.id AND ls.station_code=stage.station_code
                WHERE stage.batch_id=%(batch_id)s::uuid
                GROUP BY stage.trip_code, line.id, calendar.id
            )
            INSERT INTO trip (
                timetable_version_id, line_id, service_id, trip_code, train_number,
                direction, origin_line_station_id, destination_line_station_id, express_type
            )
            SELECT %(version_id)s::uuid, line_id, service_id, trip_code, train_number,
                   direction, origin_id, destination_id, express_type
            FROM trip_rows
            """,
            {"batch_id": batch_id, "version_id": version_id},
        )

        await connection.execute(
            """
            INSERT INTO stop_time (
                timetable_version_id, trip_id, line_station_id, stop_sequence,
                arrival_sec, departure_sec, pass_through, source_row_number
            )
            SELECT %(version_id)s::uuid, trip.id, ls.id, stage.stop_sequence,
                   stage.arrival_sec, stage.departure_sec,
                   stage.arrival_sec IS NULL AND stage.departure_sec IS NULL,
                   stage.source_row_number
            FROM ingest_stop_time_stage stage
            JOIN trip ON trip.timetable_version_id=%(version_id)s::uuid
                     AND trip.trip_code=stage.trip_code
            JOIN subway_line line ON line.code=stage.line_code
            JOIN line_station ls ON ls.line_id=line.id AND ls.station_code=stage.station_code
            WHERE stage.batch_id=%(batch_id)s::uuid
            """,
            {"batch_id": batch_id, "version_id": version_id},
        )

    @staticmethod
    async def _materialize_default_transfers(connection: DbConnection) -> None:
        await connection.execute(
            """
            WITH station_lines AS (
                SELECT
                    ls.id AS line_station_id,
                    ls.line_id,
                    regexp_replace(s.name_ko, '역$', '') AS station_name
                FROM line_station ls
                JOIN station s ON s.id=ls.station_id
                WHERE ls.active AND s.active
            )
            INSERT INTO transfer_connection (
                from_line_station_id,
                to_line_station_id,
                minimum_transfer_seconds,
                bidirectional,
                source_type,
                metadata
            )
            SELECT
                origin.line_station_id,
                destination.line_station_id,
                300,
                false,
                'DEFAULT_ESTIMATE',
                jsonb_build_object(
                    'reason', 'same normalized station name on different active lines',
                    'station_name', origin.station_name
                )
            FROM station_lines origin
            JOIN station_lines destination
              ON destination.station_name=origin.station_name
             AND destination.line_id<>origin.line_id
             AND destination.line_station_id<>origin.line_station_id
            ON CONFLICT DO NOTHING
            """
        )

    @staticmethod
    async def _materialize_travel_time_edges(
        connection: DbConnection,
        version_id: str,
    ) -> None:
        await connection.execute(
            "DELETE FROM travel_time_edge WHERE timetable_version_id=%s::uuid",
            (version_id,),
        )
        await connection.execute(
            """
            WITH ordered AS (
                SELECT
                    t.timetable_version_id,
                    t.line_id,
                    st.line_station_id AS from_line_station_id,
                    COALESCE(st.departure_sec, st.arrival_sec) AS departure_sec,
                    lead(st.line_station_id) OVER (
                        PARTITION BY t.id ORDER BY st.stop_sequence
                    ) AS to_line_station_id,
                    lead(COALESCE(st.arrival_sec, st.departure_sec)) OVER (
                        PARTITION BY t.id ORDER BY st.stop_sequence
                    ) AS next_arrival_sec
                FROM trip t
                JOIN stop_time st
                  ON st.timetable_version_id=t.timetable_version_id AND st.trip_id=t.id
                WHERE t.timetable_version_id=%(version_id)s::uuid
            ), valid_edges AS (
                SELECT *, next_arrival_sec - departure_sec AS travel_seconds
                FROM ordered
                WHERE to_line_station_id IS NOT NULL
                  AND to_line_station_id <> from_line_station_id
                  AND departure_sec IS NOT NULL
                  AND next_arrival_sec > departure_sec
                  AND next_arrival_sec - departure_sec BETWEEN 30 AND 7200
            )
            INSERT INTO travel_time_edge (
                timetable_version_id, line_id, from_line_station_id,
                to_line_station_id, travel_seconds, sample_count
            )
            SELECT
                timetable_version_id,
                line_id,
                from_line_station_id,
                to_line_station_id,
                percentile_disc(0.5) WITHIN GROUP (ORDER BY travel_seconds)::integer,
                count(*)::integer
            FROM valid_edges
            GROUP BY timetable_version_id, line_id,
                     from_line_station_id, to_line_station_id
            """,
            {"version_id": version_id},
        )

    @staticmethod
    async def _activate(
        connection: DbConnection,
        source_id: str,
        version_id: str,
        activated_by: str,
    ) -> None:
        await connection.execute(
            """
            UPDATE timetable_version old
            SET state='RETIRED'
            WHERE old.source_id=%(source_id)s::uuid AND old.id<>%(version_id)s::uuid
              AND old.state='ACTIVE'
              AND EXISTS (
                  SELECT 1 FROM timetable_activation active
                  WHERE active.source_id=%(source_id)s::uuid
                    AND active.timetable_version_id=old.id
                    AND active.line_id IN (
                        SELECT DISTINCT line_id FROM trip
                        WHERE timetable_version_id=%(version_id)s::uuid
                    )
              )
            """,
            {"source_id": source_id, "version_id": version_id},
        )
        await connection.execute(
            """
            INSERT INTO timetable_activation (
                source_id, line_id, timetable_version_id, activated_by
            )
            SELECT %(source_id)s::uuid, line_id, %(version_id)s::uuid, %(activated_by)s
            FROM (SELECT DISTINCT line_id FROM trip WHERE timetable_version_id=%(version_id)s::uuid) lines
            ON CONFLICT (source_id, line_id) DO UPDATE SET
                timetable_version_id=EXCLUDED.timetable_version_id,
                activated_at=now(), activated_by=EXCLUDED.activated_by
            """,
            {
                "source_id": source_id,
                "version_id": version_id,
                "activated_by": activated_by,
            },
        )
        await connection.execute(
            "UPDATE timetable_version SET state='ACTIVE', row_count=(SELECT count(*) FROM stop_time WHERE timetable_version_id=%s::uuid) WHERE id=%s::uuid",
            (version_id, version_id),
        )

    @staticmethod
    async def _finish_batch(
        connection: DbConnection,
        batch_id: str,
        parsed: int,
        *,
        accepted: int,
        rejected: int,
    ) -> None:
        await connection.execute(
            """
            UPDATE ingest_batch SET finished_at=now(), parsed_rows=%s,
                accepted_rows=%s, rejected_rows=%s WHERE id=%s::uuid
            """,
            (parsed, accepted, rejected, batch_id),
        )
