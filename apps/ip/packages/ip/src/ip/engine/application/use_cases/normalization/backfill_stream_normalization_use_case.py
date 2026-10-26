"""Chunked Stream Normalization Backfill Use Case.

Re-normalizes all Layer 2 replica snapshots for a stream in bounded keyset-paginated
chunks (`while True` loop + `await asyncio.sleep(0.1)` yield) after a mapper version
promotion or binding update, without locking PostgreSQL tables.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id
from structlog.typing import FilteringBoundLogger

from ip.engine.application.use_cases.normalization.normalize_replica_record_use_case import (
    NormalizeReplicaRecordCommand,
    NormalizeReplicaRecordUseCase,
)
from ip.engine.domain.enums import NormalizationOutcome
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort

logger = structlog.get_logger(__name__)

DEFAULT_BACKFILL_CHUNK_SIZE = 100
BACKFILL_CHUNK_YIELD_SECONDS = 0.1


@dataclass(frozen=True)
class BackfillStreamNormalizationCommand:
    """Command to re-normalize a stream's replica records in bounded chunks."""

    tenant_id: str
    connection_id: str
    stream: str
    trace_id: str | None = None
    correlation_id: str | None = None
    chunk_size: int = DEFAULT_BACKFILL_CHUNK_SIZE


@dataclass(frozen=True)
class BackfillStreamNormalizationResultDTO:
    """Summary of a chunked stream normalization backfill run."""

    processed_count: int
    normalized_count: int
    rejected_count: int
    tombstoned_count: int
    skipped_count: int
    chunks_processed: int


class BackfillStreamNormalizationUseCase:
    """Chunked backfill orchestrator for Layer 3 stream re-normalization."""

    def __init__(
        self,
        data_plane_uow_provider: IpDataPlaneUnitOfWorkProviderPort,
        normalize_use_case: NormalizeReplicaRecordUseCase,
    ) -> None:
        self._data_plane_uow_provider = data_plane_uow_provider
        self._normalize_use_case = normalize_use_case

    async def execute(
        self,
        command: BackfillStreamNormalizationCommand,
    ) -> Result[BackfillStreamNormalizationResultDTO, IpError]:
        """Iterate over stream replica records in bounded chunks and normalize each record."""
        trace_id = command.trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        bound_logger: FilteringBoundLogger = logger.bind(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            trace_id=trace_id,
            chunk_size=command.chunk_size,
        )
        bound_logger.info("l3_stream_backfill_started")

        shard_info_result = await self._data_plane_uow_provider.resolve_shard_info(
            command.tenant_id
        )
        if shard_info_result.is_err:
            bound_logger.error(
                "tenant_shard_resolution_failed",
                error=shard_info_result.unwrap_err().message,
            )
            return Result.err(shard_info_result.unwrap_err())

        shard_id, shard_dsn = shard_info_result.unwrap()

        processed_count = 0
        normalized_count = 0
        rejected_count = 0
        tombstoned_count = 0
        skipped_count = 0
        chunks_processed = 0
        after_id: str | None = None

        while True:
            async with self._data_plane_uow_provider.get_data_plane_uow(
                command.tenant_id, shard_id, shard_dsn
            ) as uow:
                chunk = await uow.replica_records.list_by_stream_chunk(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    stream=command.stream,
                    after_id=after_id,
                    limit=command.chunk_size,
                )

            if not chunk:
                break

            chunks_processed += 1
            for replica in chunk:
                norm_result = await self._normalize_use_case.execute(
                    NormalizeReplicaRecordCommand(
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        stream=command.stream,
                        replica_record_id=replica.id,
                        replica_version=replica.version,
                        trace_id=trace_id,
                        correlation_id=command.correlation_id or replica.correlation_id,
                        original_trace_id=replica.trace_id,
                    )
                )
                if norm_result.is_err:
                    bound_logger.error(
                        "l3_stream_backfill_record_failed",
                        replica_record_id=replica.id,
                        error=norm_result.unwrap_err().message,
                    )
                    return Result.err(norm_result.unwrap_err())

                dto = norm_result.unwrap()
                processed_count += 1
                if dto.outcome == NormalizationOutcome.NORMALIZED:
                    normalized_count += 1
                elif dto.outcome == NormalizationOutcome.REJECTED:
                    rejected_count += 1
                elif dto.outcome == NormalizationOutcome.TOMBSTONED:
                    tombstoned_count += 1
                else:
                    skipped_count += 1

            after_id = chunk[-1].id
            await asyncio.sleep(BACKFILL_CHUNK_YIELD_SECONDS)

        bound_logger.info(
            "l3_stream_backfill_completed",
            processed_count=processed_count,
            normalized_count=normalized_count,
            rejected_count=rejected_count,
            tombstoned_count=tombstoned_count,
            skipped_count=skipped_count,
            chunks_processed=chunks_processed,
        )
        return Result.ok(
            BackfillStreamNormalizationResultDTO(
                processed_count=processed_count,
                normalized_count=normalized_count,
                rejected_count=rejected_count,
                tombstoned_count=tombstoned_count,
                skipped_count=skipped_count,
                chunks_processed=chunks_processed,
            )
        )
