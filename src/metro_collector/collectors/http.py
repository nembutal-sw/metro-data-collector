from __future__ import annotations

import asyncio
import hashlib
import ssl
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from metro_collector.collectors.quota import ApiQuotaGuard, ApiRequestPolicy
from metro_collector.domain.models import CollectedArtifact


@dataclass(frozen=True, slots=True)
class ConditionalRequest:
    etag: str | None = None
    last_modified: str | None = None


class ArtifactDownloader:
    def __init__(
        self,
        *,
        timeout_seconds: float,
        max_retries: int,
        timezone: ZoneInfo,
        quota_guard: ApiQuotaGuard | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._max_retries = max_retries
        self._timezone = timezone
        self._quota_guard = quota_guard

    async def download(
        self,
        *,
        source_code: str,
        url: str,
        destination: Path,
        recorded_url: str | None = None,
        conditional: ConditionalRequest | None = None,
        api_policy: ApiRequestPolicy | None = None,
        verify_tls: bool = True,
    ) -> CollectedArtifact | None:
        headers = {
            "User-Agent": "MetroDataCollector/0.1 (+official-public-data-collector)",
            "Accept": (
                "text/csv,application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet,application/zip,application/octet-stream,*/*;q=0.8"
            ),
        }
        if conditional and conditional.etag:
            headers["If-None-Match"] = conditional.etag
        if conditional and conditional.last_modified:
            headers["If-Modified-Since"] = conditional.last_modified

        response = await self._request(
            url,
            headers,
            api_policy=api_policy,
            verify_tls=verify_tls,
        )
        if response.status_code == httpx.codes.NOT_MODIFIED:
            return None
        response.raise_for_status()

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = destination.with_suffix(destination.suffix + ".part")
        digest = hashlib.sha256()
        with temporary_path.open("wb") as output:
            async for chunk in response.aiter_bytes():
                digest.update(chunk)
                output.write(chunk)
        temporary_path.replace(destination)

        return CollectedArtifact(
            source_code=source_code,
            source_url=recorded_url or url,
            retrieved_at=datetime.now(tz=self._timezone),
            checksum=digest.hexdigest(),
            content_type=response.headers.get("content-type"),
            path=destination,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )

    async def _request(
        self,
        url: str,
        headers: dict[str, str],
        *,
        api_policy: ApiRequestPolicy | None,
        verify_tls: bool,
    ) -> httpx.Response:
        attempts = max(1, self._max_retries + 1)
        last_error: Exception | None = None
        tls_verification: bool | ssl.SSLContext = verify_tls
        if not verify_tls:
            # A few operator sites still present certificate chains/signatures that
            # OpenSSL 3 rejects at its default security level. This exception is
            # opt-in per official public source; payloads remain subject to hash and
            # structural quality gates before activation.
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            with suppress(ssl.SSLError):
                context.set_ciphers("DEFAULT:@SECLEVEL=0")
            tls_verification = context
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            verify=tls_verification,
        ) as client:
            for attempt in range(attempts):
                if api_policy is not None:
                    if self._quota_guard is None:
                        raise RuntimeError("An API request policy requires an ApiQuotaGuard")
                    await self._quota_guard.reserve(api_policy)
                try:
                    response = await client.get(url, headers=headers)
                except (httpx.TimeoutException, httpx.NetworkError) as error:
                    last_error = error
                    if attempt + 1 >= attempts:
                        raise
                    await asyncio.sleep(min(8.0, 0.5 * (2**attempt)))
                    continue

                if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
                    retry_after = self._retry_after_seconds(response)
                    if api_policy is not None and self._quota_guard is not None:
                        await self._quota_guard.block(
                            api_policy.provider,
                            retry_after_seconds=retry_after,
                            status_code=response.status_code,
                        )
                    if attempt + 1 >= attempts:
                        return response
                    await asyncio.sleep(retry_after)
                    continue
                if response.status_code >= 500 and attempt + 1 < attempts:
                    await asyncio.sleep(min(8.0, 0.5 * (2**attempt)))
                    continue
                return response
        if last_error is not None:
            raise last_error
        raise RuntimeError("HTTP request loop completed without a response")

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float:
        value = response.headers.get("retry-after")
        if not value:
            return 60.0
        try:
            return max(1.0, float(value))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                return 60.0
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=UTC)
            return max(1.0, (retry_at - datetime.now(UTC)).total_seconds())
