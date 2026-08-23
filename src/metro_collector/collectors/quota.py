from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from metro_collector.db import Database
from metro_collector.exceptions import ApiQuotaExceeded, ApiRateLimitBlocked


@dataclass(frozen=True, slots=True)
class ApiRequestPolicy:
    provider: str
    daily_budget: int
    minimum_interval_seconds: float

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValueError("API provider must not be empty")
        if self.daily_budget <= 0:
            raise ValueError("API daily budget must be positive")
        if self.minimum_interval_seconds < 0:
            raise ValueError("API minimum interval must not be negative")


class ApiQuotaGuard:
    """Persist request reservations so restarts cannot reset API budgets."""

    def __init__(self, database: Database, timezone: ZoneInfo) -> None:
        self._database = database
        self._timezone = timezone

    async def reserve(self, policy: ApiRequestPolicy) -> int:
        while True:
            now = datetime.now(tz=self._timezone)
            wait_seconds = 0.0
            async with self._database.transaction() as connection:
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"api-quota:{policy.provider}",),
                )
                cursor = await connection.execute(
                    """
                    SELECT request_count, last_requested_at, blocked_until
                    FROM external_api_request_usage
                    WHERE provider=%s AND usage_date=%s
                    """,
                    (policy.provider, now.date()),
                )
                row = await cursor.fetchone()
                if row and row["blocked_until"] and row["blocked_until"] > now:
                    raise ApiRateLimitBlocked(
                        f"{policy.provider} API is blocked until "
                        f"{row['blocked_until'].isoformat()}"
                    )
                request_count = int(row["request_count"]) if row else 0
                if request_count >= policy.daily_budget:
                    raise ApiQuotaExceeded(
                        f"{policy.provider} daily request budget "
                        f"({policy.daily_budget}) is exhausted"
                    )
                if row and row["last_requested_at"]:
                    elapsed = (now - row["last_requested_at"]).total_seconds()
                    wait_seconds = max(0.0, policy.minimum_interval_seconds - elapsed)
                if wait_seconds == 0:
                    cursor = await connection.execute(
                        """
                        INSERT INTO external_api_request_usage (
                            provider, usage_date, request_count, last_requested_at
                        ) VALUES (%s, %s, 1, %s)
                        ON CONFLICT (provider, usage_date) DO UPDATE SET
                            request_count=external_api_request_usage.request_count + 1,
                            last_requested_at=EXCLUDED.last_requested_at,
                            updated_at=now()
                        RETURNING request_count
                        """,
                        (policy.provider, now.date(), now),
                    )
                    reserved = await cursor.fetchone()
                    if reserved is None:
                        raise RuntimeError("Failed to reserve an external API request")
                    return int(reserved["request_count"])
            await asyncio.sleep(wait_seconds)

    async def block(
        self,
        provider: str,
        *,
        retry_after_seconds: float,
        status_code: int,
    ) -> None:
        now = datetime.now(tz=self._timezone)
        blocked_until = now + timedelta(seconds=max(1.0, retry_after_seconds))
        async with self._database.transaction() as connection:
            await connection.execute(
                """
                INSERT INTO external_api_request_usage (
                    provider, usage_date, request_count, last_requested_at,
                    blocked_until, last_status
                ) VALUES (%s, %s, 0, %s, %s, %s)
                ON CONFLICT (provider, usage_date) DO UPDATE SET
                    blocked_until=GREATEST(
                        external_api_request_usage.blocked_until,
                        EXCLUDED.blocked_until
                    ),
                    last_status=EXCLUDED.last_status,
                    updated_at=now()
                """,
                (provider, now.date(), now, blocked_until, status_code),
            )
