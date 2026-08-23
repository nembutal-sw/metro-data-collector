from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

type DbConnection = AsyncConnection[dict[str, Any]]


class Database:
    def __init__(self, database_url: str) -> None:
        self._pool = cast(
            AsyncConnectionPool[DbConnection],
            AsyncConnectionPool(
                conninfo=database_url,
                min_size=1,
                max_size=10,
                open=False,
                kwargs={"row_factory": dict_row, "autocommit": False},
                check=AsyncConnectionPool.check_connection,
            ),
        )

    async def open(self) -> None:
        await self._pool.open(wait=True)

    async def close(self) -> None:
        await self._pool.close()

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[DbConnection]:
        async with self._pool.connection() as connection:
            yield connection

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[DbConnection]:
        async with self._pool.connection() as connection, connection.transaction():
            yield connection
