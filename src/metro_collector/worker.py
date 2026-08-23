from __future__ import annotations

import asyncio
import time
from datetime import datetime

import httpx
import structlog

from metro_collector.collectors.base import CollectorRegistry
from metro_collector.collectors.incheon import IncheonTransitCollector
from metro_collector.collectors.korail_kric import KorailKricTimetableCollector
from metro_collector.collectors.kric_standard import build_kric_standard_collectors
from metro_collector.collectors.official_operators import build_official_operator_collectors
from metro_collector.collectors.seoul_open_data import SeoulOpenDataCollector
from metro_collector.collectors.seoul_transfer import SeoulTransferDistanceCollector
from metro_collector.collectors.station_coordinates import KricStationCoordinateCollector
from metro_collector.config import Settings
from metro_collector.db import Database
from metro_collector.domain.enums import SourceAccessStatus
from metro_collector.exceptions import ApiRateLimitBlocked, QualityGateError
from metro_collector.ingestion.coordinates import StationCoordinateIngestionService
from metro_collector.ingestion.service import TimetableIngestionService
from metro_collector.ingestion.transfer import TransferIngestionService
from metro_collector.repositories.sync_jobs import SyncJobRepository

logger = structlog.get_logger(__name__)


class SyncWorker:
    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._database = database
        self._registry = CollectorRegistry(
            [
                SeoulOpenDataCollector(settings),
                IncheonTransitCollector(settings, 1),
                IncheonTransitCollector(settings, 2),
                KorailKricTimetableCollector(settings),
                *build_official_operator_collectors(settings),
                *build_kric_standard_collectors(settings),
                SeoulTransferDistanceCollector(settings),
                KricStationCoordinateCollector(settings),
            ]
        )
        self._ingestion = TimetableIngestionService(database)
        self._transfer_ingestion = TransferIngestionService(database)
        self._coordinate_ingestion = StationCoordinateIngestionService(database)

    async def run_forever(self) -> None:
        await self._schedule_due_sources()
        next_schedule_check = time.monotonic() + 300
        while True:
            if time.monotonic() >= next_schedule_check:
                await self._schedule_due_sources()
                next_schedule_check = time.monotonic() + 300
            processed = await self.process_one()
            if not processed:
                await asyncio.sleep(5)

    async def _schedule_due_sources(self) -> None:
        async for metadata in self._registry.metadata():
            if metadata.access_status != SourceAccessStatus.ENABLED:
                continue
            async with self._database.transaction() as connection:
                await SyncJobRepository.enqueue_scheduled_if_due(
                    connection,
                    source_code=metadata.code,
                    now=datetime.now(tz=self._settings.timezone),
                )

    async def process_one(self) -> bool:
        async with self._database.transaction() as connection:
            job = await SyncJobRepository.claim_next(connection)
        if job is None:
            return False

        job_id = job["id"]
        source_code = job["source_code"]
        artifact_checksum: str | None = None
        try:
            collector = await self._registry.by_code(source_code)
            async with self._database.connection() as connection:
                previous = await SyncJobRepository.latest_artifact(connection, source_code)
            collected = await collector.collect(previous)
            if collected is None:
                async with self._database.transaction() as connection:
                    await SyncJobRepository.finish(
                        connection,
                        job_id=job_id,
                        status="SKIPPED_UNCHANGED",
                        collected_count=0,
                        inserted_count=0,
                        artifact_checksum=previous.checksum if previous else None,
                    )
                return True

            artifact_checksum = collected.artifact.checksum
            validation = await collector.validate(collected.artifact)
            if isinstance(collector, KricStationCoordinateCollector):
                if not validation.passed:
                    raise QualityGateError(f"Source validation failed for {source_code}")
                coordinate_outcome = await self._coordinate_ingestion.ingest(
                    source_code=source_code,
                    artifact=collected.artifact,
                    records=collector.iter_coordinates(collected.artifact),
                )
                async with self._database.transaction() as connection:
                    await SyncJobRepository.finish(
                        connection,
                        job_id=job_id,
                        status="SUCCEEDED",
                        collected_count=coordinate_outcome.parsed_count,
                        inserted_count=coordinate_outcome.updated_count,
                        artifact_checksum=artifact_checksum,
                    )
                return True
            if isinstance(collector, SeoulTransferDistanceCollector):
                if not validation.passed:
                    raise QualityGateError(f"Source validation failed for {source_code}")
                transfer_outcome = await self._transfer_ingestion.ingest(
                    source_code=source_code,
                    source_url=collected.artifact.source_url,
                    artifact=collected.artifact,
                    records=collector.iter_transfers(collected.artifact),
                    effective_from=collected.effective_from,
                )
                async with self._database.transaction() as connection:
                    await SyncJobRepository.finish(
                        connection,
                        job_id=job_id,
                        status="SUCCEEDED",
                        collected_count=transfer_outcome.parsed_count,
                        inserted_count=transfer_outcome.inserted_count,
                        artifact_checksum=artifact_checksum,
                    )
                return True
            outcome = await self._ingestion.ingest(
                source_code=source_code,
                artifact=collected.artifact,
                records=collector.iter_records(collected.artifact),
                effective_from=collected.effective_from,
                effective_to=collected.effective_to,
                source_validation=validation,
                activated_by="sync-worker",
            )
            status = "SUCCEEDED" if outcome.activated else "FAILED"
            async with self._database.transaction() as connection:
                await SyncJobRepository.finish(
                    connection,
                    job_id=job_id,
                    status=status,
                    collected_count=outcome.row_count,
                    inserted_count=outcome.row_count if outcome.activated else 0,
                    artifact_checksum=artifact_checksum,
                )
            return True
        except Exception as error:
            retryable = isinstance(
                error,
                (httpx.TimeoutException, httpx.NetworkError, ApiRateLimitBlocked),
            )
            logger.exception("sync_job_failed", job_id=job_id, source_code=source_code)
            async with self._database.transaction() as connection:
                await SyncJobRepository.fail(
                    connection,
                    job_id=job_id,
                    stage="COLLECT_OR_INGEST",
                    error=error,
                    retryable=retryable,
                )
            return True
