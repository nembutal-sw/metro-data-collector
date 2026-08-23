from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from metro_collector.db import DbConnection
from metro_collector.domain.models import CollectedArtifact


class SyncJobRepository:
    @staticmethod
    async def enqueue(
        connection: DbConnection,
        *,
        source_code: str,
        requested_by: str,
        now: datetime,
    ) -> dict[str, Any]:
        idempotency_key = f"{source_code}:MANUAL:{now.isoformat()}:{uuid4()}"
        cursor = await connection.execute(
            """
            INSERT INTO sync_job (source_id, status, trigger_type, requested_by, idempotency_key)
            SELECT id, 'PENDING', 'MANUAL', %(requested_by)s, %(idempotency_key)s
            FROM source_registry
            WHERE code = %(source_code)s AND access_status = 'ENABLED'
            RETURNING id::text, status, trigger_type, requested_by, created_at
            """,
            {
                "source_code": source_code,
                "requested_by": requested_by,
                "idempotency_key": idempotency_key,
            },
        )
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"Enabled source not found: {source_code}")
        return dict(row)

    @staticmethod
    async def list_recent(
        connection: DbConnection,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        cursor = await connection.execute(
            """
            SELECT j.id::text, s.code AS source_code, s.name AS source_name, j.status,
                   j.trigger_type, j.requested_by, j.started_at, j.finished_at,
                   j.collected_count, j.inserted_count, j.error_count, j.created_at
            FROM sync_job j
            JOIN source_registry s ON s.id = j.source_id
            ORDER BY j.created_at DESC
            LIMIT %(limit)s
            """,
            {"limit": limit},
        )
        return list(await cursor.fetchall())

    @staticmethod
    async def enqueue_scheduled_if_due(
        connection: DbConnection,
        *,
        source_code: str,
        now: datetime,
    ) -> None:
        idempotency_key = f"{source_code}:SCHEDULED:{now.date().isoformat()}"
        await connection.execute(
            """
            INSERT INTO sync_job (source_id, status, trigger_type, requested_by, idempotency_key)
            SELECT id, 'PENDING', 'SCHEDULED', 'worker', %(idempotency_key)s
            FROM source_registry
            WHERE code=%(source_code)s AND access_status='ENABLED'
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            {"source_code": source_code, "idempotency_key": idempotency_key},
        )

    @staticmethod
    async def claim_next(connection: DbConnection) -> dict[str, Any] | None:
        cursor = await connection.execute(
            """
            WITH candidate AS (
                SELECT j.id
                FROM sync_job j
                WHERE j.status='PENDING'
                ORDER BY j.created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE sync_job job
            SET status='RUNNING', started_at=now()
            FROM candidate, source_registry source
            WHERE job.id=candidate.id AND source.id=job.source_id
            RETURNING job.id::text, source.code AS source_code
            """
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    async def latest_artifact(
        connection: DbConnection,
        source_code: str,
    ) -> CollectedArtifact | None:
        cursor = await connection.execute(
            """
            SELECT source.code AS source_code, artifact.source_url, artifact.retrieved_at,
                   artifact.checksum, artifact.content_type, artifact.storage_path,
                   artifact.etag, artifact.last_modified
            FROM source_artifact artifact
            JOIN source_registry source ON source.id=artifact.source_id
            WHERE source.code=%s AND artifact.storage_path IS NOT NULL
            ORDER BY artifact.retrieved_at DESC LIMIT 1
            """,
            (source_code,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        from pathlib import Path

        return CollectedArtifact(
            source_code=row["source_code"],
            source_url=row["source_url"],
            retrieved_at=row["retrieved_at"],
            checksum=row["checksum"],
            content_type=row["content_type"],
            path=Path(row["storage_path"]),
            etag=row["etag"],
            last_modified=row["last_modified"],
        )

    @staticmethod
    async def finish(
        connection: DbConnection,
        *,
        job_id: str,
        status: str,
        collected_count: int,
        inserted_count: int,
        artifact_checksum: str | None,
    ) -> None:
        await connection.execute(
            """
            UPDATE sync_job SET status=%(status)s, finished_at=now(),
                collected_count=%(collected_count)s, inserted_count=%(inserted_count)s,
                artifact_checksum=%(artifact_checksum)s
            WHERE id=%(job_id)s::uuid
            """,
            {
                "job_id": job_id,
                "status": status,
                "collected_count": collected_count,
                "inserted_count": inserted_count,
                "artifact_checksum": artifact_checksum,
            },
        )

    @staticmethod
    async def fail(
        connection: DbConnection,
        *,
        job_id: str,
        stage: str,
        error: Exception,
        retryable: bool,
    ) -> None:
        await connection.execute(
            """
            UPDATE sync_job SET status='FAILED', finished_at=now(), error_count=error_count+1
            WHERE id=%s::uuid
            """,
            (job_id,),
        )
        await connection.execute(
            """
            INSERT INTO sync_job_error (sync_job_id, stage, error_code, message, retryable)
            VALUES (%s::uuid, %s, %s, %s, %s)
            """,
            (job_id, stage, type(error).__name__, str(error)[:2000], retryable),
        )
