from __future__ import annotations

import hmac
from hashlib import sha256
from typing import Annotated, cast

from fastapi import Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, APIKeyQuery

from metro_collector.config import Settings, get_settings
from metro_collector.db import Database

public_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
public_api_key_query = APIKeyQuery(name="apiKey", auto_error=False)


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


async def require_admin_key(
    x_admin_api_key: Annotated[str | None, Header()] = None,
) -> str:
    settings: Settings = get_settings()
    configured = settings.admin_api_key
    expected = configured.get_secret_value() if configured else ""
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ADMIN_API_KEY is not configured",
        )
    if not x_admin_api_key or not hmac.compare_digest(x_admin_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid administrator API key",
        )
    return "admin"


async def require_public_api_key(
    x_api_key: str | None = Security(public_api_key_header),
    api_key: str | None = Security(public_api_key_query),
) -> str:
    configured_hashes = get_settings().public_api_key_hash_values
    if not configured_hashes:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PUBLIC_API_KEY_HASHES is not configured",
        )

    candidate = x_api_key or api_key
    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key is required",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    candidate_hash = sha256(candidate.encode("utf-8")).hexdigest()
    if not any(hmac.compare_digest(candidate_hash, expected) for expected in configured_hashes):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return candidate_hash[:12]
