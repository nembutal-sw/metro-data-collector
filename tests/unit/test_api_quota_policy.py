import httpx
import pytest

from metro_collector.collectors.http import ArtifactDownloader
from metro_collector.collectors.quota import ApiRequestPolicy


def test_api_request_policy_requires_positive_budget() -> None:
    with pytest.raises(ValueError):
        ApiRequestPolicy(provider="DATA_GO_KR", daily_budget=0, minimum_interval_seconds=1)


def test_retry_after_supports_seconds() -> None:
    response = httpx.Response(429, headers={"Retry-After": "17"})
    assert ArtifactDownloader._retry_after_seconds(response) == 17
