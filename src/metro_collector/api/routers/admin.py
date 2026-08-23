from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from metro_collector.api.dependencies import get_database, require_admin_key
from metro_collector.config import get_settings
from metro_collector.db import Database
from metro_collector.repositories.sync_jobs import SyncJobRepository

router = APIRouter(prefix="/api/v1", tags=["operations"])


@router.get("/sync/jobs")
async def sync_jobs(
    limit: int = Query(default=100, ge=1, le=500),
    database: Database = Depends(get_database),
) -> list[dict[str, Any]]:
    async with database.connection() as connection:
        return await SyncJobRepository.list_recent(connection, limit=limit)


@router.post("/admin/sync/{source_code}", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_sync(
    source_code: str,
    actor: str = Depends(require_admin_key),
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    try:
        async with database.transaction() as connection:
            return await SyncJobRepository.enqueue(
                connection,
                source_code=source_code,
                requested_by=actor,
                now=datetime.now(tz=get_settings().timezone),
            )
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
