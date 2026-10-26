"""Use case for deterministic multi-stage transaction replay across L1, L2, L3, and L5."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from ip.engine.application.dtos.trace import IpTraceDTO, ReplayTransactionResultDTO
from ip.engine.application.use_cases.transactions.get_ip_trace_use_case import GetIpTraceUseCase
from ip.engine.domain.enums import ReplayStage
from ip.engine.domain.exceptions import (
    IpError,
    ReplayStageNotAvailableError,
    Result,
    TraceNotFoundError,
)
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ReplayTransactionCommand:
    """Command to replay an existing Integration Platform transaction from a specific stage."""

    tenant_id: str
    trace_id: str
    stage: ReplayStage
    actor: str = "SYSTEM"
    modified_payload: JsonDict | None = None


class ReplayTransactionUseCase:
    """Replays an Integration Platform transaction from L1, L2, L3, or L5 while preserving lineage."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider

    async def execute(
        self, command: ReplayTransactionCommand
    ) -> Result[ReplayTransactionResultDTO, IpError]:
        shard_res = await self._uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())

        shard_id, shard_dsn = shard_res.unwrap()
        async with self._uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            res = await self.replay_in_uow(uow, command)
            if res.is_err:
                return res
            await uow.commit()
            return res

    async def _replay_ingest(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: ReplayTransactionCommand,
        trace: IpTraceDTO,
        new_trace_id: str,
        next_replay_count: int,
    ) -> Result[ReplayTransactionResultDTO, IpError]:
        if trace.inbound_record is None:
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    command.trace_id,
                    command.stage.value,
                    f"Trace '{command.trace_id}' has no L1 InboundRecord to replay.",
                )
            )
        cloned_inb = trace.inbound_record.clone_for_replay(
            new_trace_id=new_trace_id,
            parent_trace_id=command.trace_id,
            original_trace_id=trace.original_trace_id,
            replay_count=next_replay_count,
            modified_request_body=(
                dict(command.modified_payload) if command.modified_payload is not None else None
            ),
            actor=command.actor,
        )
        await uow.inbound_records.save(cloned_inb)
        return Result.ok(
            ReplayTransactionResultDTO(
                original_trace_id=cloned_inb.original_trace_id or command.trace_id,
                parent_trace_id=command.trace_id,
                new_trace_id=new_trace_id,
                stage=command.stage,
                replay_count=cloned_inb.replay_count,
                correlation_id=cloned_inb.correlation_id,
            )
        )

    async def _replay_normalize(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: ReplayTransactionCommand,
        trace: IpTraceDTO,
        new_trace_id: str,
        next_replay_count: int,
    ) -> Result[ReplayTransactionResultDTO, IpError]:
        if not trace.replica_records:
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    command.trace_id,
                    command.stage.value,
                    f"Trace '{command.trace_id}' has no L2 ReplicaRecord to normalize.",
                )
            )
        for idx, replica in enumerate(trace.replica_records):
            replica.trace_id = command.trace_id
            replica.original_trace_id = trace.original_trace_id
            replica.replay_count = trace.replay_count
            replica.schedule_normalization_replay(
                new_trace_id=new_trace_id,
                actor=command.actor,
            )
            if idx > 0:
                replica.clear_trace_events()
            await uow.replica_records.save(replica)

        return Result.ok(
            ReplayTransactionResultDTO(
                original_trace_id=trace.original_trace_id,
                parent_trace_id=command.trace_id,
                new_trace_id=new_trace_id,
                stage=command.stage,
                replay_count=next_replay_count,
                correlation_id=trace.correlation_id,
            )
        )

    async def _replay_stitch(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: ReplayTransactionCommand,
        trace: IpTraceDTO,
        new_trace_id: str,
        next_replay_count: int,
    ) -> Result[ReplayTransactionResultDTO, IpError]:
        if not trace.normalized_records:
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    command.trace_id,
                    command.stage.value,
                    f"Trace '{command.trace_id}' has no L3 NormalizedRecord to stitch.",
                )
            )
        target_records = (
            (trace.normalized_records[-1],)
            if command.modified_payload is not None
            else trace.normalized_records
        )
        for idx, norm in enumerate(target_records):
            cloned_norm = norm.clone_for_replay(
                new_trace_id=new_trace_id,
                parent_trace_id=command.trace_id,
                original_trace_id=trace.original_trace_id,
                replay_count=next_replay_count,
                modified_canonical_data=(
                    dict(command.modified_payload) if command.modified_payload is not None else None
                ),
                actor=command.actor,
            )
            if idx > 0:
                cloned_norm.clear_trace_events()
            await uow.normalized_records.save(cloned_norm)

        return Result.ok(
            ReplayTransactionResultDTO(
                original_trace_id=trace.original_trace_id,
                parent_trace_id=command.trace_id,
                new_trace_id=new_trace_id,
                stage=command.stage,
                replay_count=next_replay_count,
                correlation_id=trace.correlation_id,
            )
        )

    async def _replay_deliver(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: ReplayTransactionCommand,
        trace: IpTraceDTO,
        new_trace_id: str,
        next_replay_count: int,
    ) -> Result[ReplayTransactionResultDTO, IpError]:
        if not trace.outbound_records:
            return Result.err(
                ReplayStageNotAvailableError.for_stage(
                    command.trace_id,
                    command.stage.value,
                    f"Trace '{command.trace_id}' has no L5 OutboundRecord to deliver.",
                )
            )
        latest_outbound = trace.outbound_records[-1]
        cloned_out = latest_outbound.clone_for_delivery_retry(
            new_trace_id=new_trace_id,
            parent_trace_id=command.trace_id,
            original_trace_id=trace.original_trace_id,
            replay_count=next_replay_count,
            actor=command.actor,
        )
        await uow.outbound_records.save(cloned_out)
        return Result.ok(
            ReplayTransactionResultDTO(
                original_trace_id=trace.original_trace_id,
                parent_trace_id=command.trace_id,
                new_trace_id=new_trace_id,
                stage=command.stage,
                replay_count=next_replay_count,
                correlation_id=trace.correlation_id,
            )
        )

    async def replay_in_uow(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        command: ReplayTransactionCommand,
    ) -> Result[ReplayTransactionResultDTO, IpError]:
        trace = await GetIpTraceUseCase.assemble_in_uow(
            uow,
            tenant_id=command.tenant_id,
            trace_id=command.trace_id,
            hydrate_payloads=False,
        )
        if trace is None:
            return Result.err(TraceNotFoundError.for_trace(command.trace_id))

        new_trace_id = generate_id(DomainIdPrefix.IP_TRACE.value)
        next_replay_count = trace.replay_count + 1

        if command.stage == ReplayStage.RETRY_INGEST:
            res = await self._replay_ingest(uow, command, trace, new_trace_id, next_replay_count)
        elif command.stage == ReplayStage.RETRY_NORMALIZE:
            res = await self._replay_normalize(uow, command, trace, new_trace_id, next_replay_count)
        elif command.stage == ReplayStage.RETRY_STITCH:
            res = await self._replay_stitch(uow, command, trace, new_trace_id, next_replay_count)
        else:
            res = await self._replay_deliver(uow, command, trace, new_trace_id, next_replay_count)

        if res.is_ok:
            dto = res.unwrap()
            log_event = (
                "ip_transaction_modified_and_replayed"
                if command.modified_payload is not None
                else "ip_transaction_replayed"
            )
            logger.info(
                log_event,
                tenant_id=command.tenant_id,
                stage=command.stage.value,
                parent_trace_id=command.trace_id,
                original_trace_id=dto.original_trace_id,
                new_trace_id=dto.new_trace_id,
                replay_count=dto.replay_count,
                actor=command.actor,
            )
        return res


__all__ = ["ReplayTransactionCommand", "ReplayTransactionUseCase"]
