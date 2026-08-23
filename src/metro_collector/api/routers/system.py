from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from metro_collector.api.dependencies import get_database
from metro_collector.db import Database

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(database: Database = Depends(get_database)) -> dict[str, str]:
    try:
        async with database.connection() as connection:
            cursor = await connection.execute("SELECT 1 AS healthy")
            await cursor.fetchone()
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable",
        ) from error
    return {"status": "ok", "database": "ok"}
