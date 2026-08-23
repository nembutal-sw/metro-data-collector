from hashlib import sha256

import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from metro_collector.api import dependencies
from metro_collector.config import Settings


@pytest.fixture
def configured_public_key(monkeypatch: pytest.MonkeyPatch) -> str:
    raw_key = "metro_live_test_key"
    digest = sha256(raw_key.encode("utf-8")).hexdigest()
    settings = Settings(public_api_key_hashes=SecretStr(digest))
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    return raw_key


async def test_accepts_public_key_from_header_or_query(configured_public_key: str) -> None:
    from_header = await dependencies.require_public_api_key(configured_public_key, None)
    from_query = await dependencies.require_public_api_key(None, configured_public_key)

    assert from_header == from_query
    assert len(from_header) == 12


async def test_rejects_missing_or_invalid_public_key(configured_public_key: str) -> None:
    del configured_public_key
    with pytest.raises(HTTPException) as missing:
        await dependencies.require_public_api_key(None, None)
    with pytest.raises(HTTPException) as invalid:
        await dependencies.require_public_api_key("wrong", None)

    assert missing.value.status_code == 401
    assert invalid.value.status_code == 401
