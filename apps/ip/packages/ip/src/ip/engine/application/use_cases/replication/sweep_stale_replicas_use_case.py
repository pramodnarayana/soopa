"""Use case for chunked full-refresh tombstone sweeping at Layer 2."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)

DEFAULT_SWEEP_CHUNK_SIZE = 500
DEFAULT_SWEEP_YIELD_SECONDS = 0.1


@dataclass(frozen=True)
class SweepStaleReplicasCommand:
    """Command triggered when a FULL_REFRESH generation completes."""

    tenant_id: str
    connection_id: str
    stream: str
    current_generation: int
    trace_id: str
    chunk_size: int = DEFAULT_SWEEP_CHUNK_SIZE


@dataclass(frozen=True)
class SweepStaleReplicasSummary:
    """Summary of tombstoned records across all chunks."""

    total_tombstoned: int
    chunks_processed: int


class SweepStaleReplicasUseCase:
    """Chunked tombstone sweeper soft-deleting rows with last_seen_generation < current_generation."""

    def __init__(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        yield_seconds: float = DEFAULT_SWEEP_YIELD_SECONDS,
    ) -> None:
        self._uow = uow
        self._yield_seconds = yield_seconds

    async def execute(
        self, command: SweepStaleReplicasCommand
    ) -> Result[SweepStaleReplicasSummary, IpError]:
        total_tombstoned = 0
        chunks_processed = 0
        chunk_limit = max(1, command.chunk_size)

        logger.info(
            "sweep_stale_replicas_started",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            current_generation=command.current_generation,
            trace_id=command.trace_id,
        )

        while True:
            async with self._uow:
                tombstoned_in_chunk = await self._uow.replica_records.tombstone_unseen_generations(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    stream=command.stream,
                    current_generation=command.current_generation,
                    limit=chunk_limit,
                    trace_id=command.trace_id,
                )
                if tombstoned_in_chunk > 0:
                    await self._uow.commit()

            if tombstoned_in_chunk == 0:
                break

            total_tombstoned += tombstoned_in_chunk
            chunks_processed += 1

            if tombstoned_in_chunk < chunk_limit:
                break

            await asyncio.sleep(self._yield_seconds)

        logger.info(
            "sweep_stale_replicas_completed",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream=command.stream,
            current_generation=command.current_generation,
            total_tombstoned=total_tombstoned,
            chunks_processed=chunks_processed,
            trace_id=command.trace_id,
        )

        return Result.ok(
            SweepStaleReplicasSummary(
                total_tombstoned=total_tombstoned,
                chunks_processed=chunks_processed,
            )
        )
