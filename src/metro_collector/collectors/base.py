from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Iterator

from metro_collector.domain.models import (
    ActivationResult,
    CollectedArtifact,
    CollectionResult,
    NormalizedStopTime,
    SourceMetadata,
    ValidationResult,
)


class TransitSourceCollector(ABC):
    @abstractmethod
    async def inspect(self) -> SourceMetadata:
        """Return source capabilities and collection policy status."""

    @abstractmethod
    async def collect(self, previous: CollectedArtifact | None = None) -> CollectionResult | None:
        """Collect a new artifact, or return None when the source is unchanged."""

    @abstractmethod
    def iter_records(self, artifact: CollectedArtifact) -> Iterator[NormalizedStopTime]:
        """Stream normalized records without loading the full artifact into memory."""

    @abstractmethod
    async def validate(self, artifact: CollectedArtifact) -> ValidationResult:
        """Perform source-level validation before database staging."""

    @abstractmethod
    async def activate(self, version_id: str) -> ActivationResult:
        """Activate a previously staged and validated version."""


class CollectorRegistry:
    def __init__(self, collectors: list[TransitSourceCollector]) -> None:
        self._collectors = collectors

    async def metadata(self) -> AsyncIterator[SourceMetadata]:
        for collector in self._collectors:
            yield await collector.inspect()

    async def by_code(self, code: str) -> TransitSourceCollector:
        for collector in self._collectors:
            metadata = await collector.inspect()
            if metadata.code == code:
                return collector
        raise KeyError(f"Unknown collector: {code}")
