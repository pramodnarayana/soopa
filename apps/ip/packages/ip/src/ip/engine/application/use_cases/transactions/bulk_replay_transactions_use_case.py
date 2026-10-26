"""Use case for bulk-replaying multiple Integration Platform transactions."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from ip.engine.application.dtos.trace import BulkReplayFailureItemDTO, BulkReplayResultDTO
from ip.engine.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionCommand,
    ReplayTransactionUseCase,
)
from ip.engine.domain.enums import ReplayStage
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class BulkReplayCommand:
    """Command to replay a deduplicated batch of transaction trace IDs."""

    tenant_id: str
    trace_ids: tuple[str, ...]
    stage: ReplayStage
    actor: str = "SYSTEM"


class BulkReplayTransactionsUseCase:
    """Replays a batch of unique transaction traces and reports per-trace outcomes."""

    def __init__(self, uow_provider: IpDataPlaneUnitOfWorkProviderPort) -> None:
        self._uow_provider = uow_provider
        self._single_replay = ReplayTransactionUseCase(uow_provider=uow_provider)

    async def execute(self, command: BulkReplayCommand) -> Result[BulkReplayResultDTO, IpError]:
        shard_res = await self._uow_provider.resolve_shard_info(command.tenant_id)
        if shard_res.is_err:
            return Result.err(shard_res.unwrap_err())

        unique_trace_ids = list(dict.fromkeys(t for t in command.trace_ids if t))
        if not unique_trace_ids:
            return Result.ok(
                BulkReplayResultDTO(
                    stage=command.stage,
                    replayed_count=0,
                    succeeded_trace_ids=(),
                    new_trace_ids=(),
                    failed_items=(),
                )
            )

        shard_id, shard_dsn = shard_res.unwrap()
        succeeded: list[str] = []
        new_traces: list[str] = []
        failures: list[BulkReplayFailureItemDTO] = []

        async with self._uow_provider.get_data_plane_uow(
            command.tenant_id, shard_id, shard_dsn
        ) as uow:
            for trace_id in unique_trace_ids:
                res = await self._single_replay.replay_in_uow(
                    uow,
                    ReplayTransactionCommand(
                        tenant_id=command.tenant_id,
                        trace_id=trace_id,
                        stage=command.stage,
                        actor=command.actor,
                    ),
                )
                if res.is_ok:
                    dto = res.unwrap()
                    succeeded.append(trace_id)
                    new_traces.append(dto.new_trace_id)
                else:
                    err = res.unwrap_err()
                    failures.append(
                        BulkReplayFailureItemDTO(
                            trace_id=trace_id,
                            error_code=err.code,
                            message=err.message,
                        )
                    )

            if succeeded:
                await uow.commit()

        logger.info(
            "ip_bulk_transactions_replayed",
            tenant_id=command.tenant_id,
            stage=command.stage.value,
            replayed_count=len(succeeded),
            failed_count=len(failures),
            actor=command.actor,
        )
        return Result.ok(
            BulkReplayResultDTO(
                stage=command.stage,
                replayed_count=len(succeeded),
                succeeded_trace_ids=tuple(succeeded),
                new_trace_ids=tuple(new_traces),
                failed_items=tuple(failures),
            )
        )


__all__ = ["BulkReplayCommand", "BulkReplayTransactionsUseCase"]
