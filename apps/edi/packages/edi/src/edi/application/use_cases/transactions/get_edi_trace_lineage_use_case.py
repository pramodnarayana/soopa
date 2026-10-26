from collections.abc import Sequence

import structlog
from seedwork.domain.types import JsonDict
from strace.domain import (
    TraceLineageItemDTO,
    TraceStageAttemptRow,
    aggregate_trace_lineage_attempts,
)

from edi.domain.enums import EdiDirection
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger()


class GetEdiTraceLineageUseCase:
    """
    Returns the full lineage of replay attempts for a given trace.
    Finds the root/original trace id and merges stage attempts via the platform trace package.
    """

    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(self, tenant_id: str, trace_id: str) -> Sequence[TraceLineageItemDTO]:
        log = logger.bind(tenant_id=tenant_id, trace_id=trace_id)

        msg_trace = await self.uow.transactions.get_edi_message(trace_id)
        json_trace = await self.uow.transactions.get_edi_json(trace_id)

        if not msg_trace and not json_trace:
            log.warning("get_edi_trace_lineage.not_found")
            return []

        raw_direction = (
            msg_trace.direction if msg_trace else (json_trace.direction if json_trace else None)
        )
        if not raw_direction:
            return []

        direction = EdiDirection(raw_direction) if isinstance(raw_direction, str) else raw_direction

        orig_trace_id = (
            (msg_trace.original_trace_id or msg_trace.trace_id)
            if msg_trace
            else (json_trace.original_trace_id or json_trace.trace_id if json_trace else trace_id)
        )

        filters: list[JsonDict] = [
            {"field": "original_trace_id", "operator": "eq", "value": orig_trace_id},
            {"field": "direction", "operator": "eq", "value": direction.value},
        ]
        lineage_msgs = await self.uow.transactions.explorer_list_edi_messages(
            tenant_id, filters, limit=50
        )
        lineage_jsons = await self.uow.transactions.explorer_list_edi_json(
            tenant_id, filters, limit=50
        )

        root_msg = await self.uow.transactions.get_edi_message(orig_trace_id)
        root_json = await self.uow.transactions.get_edi_json(orig_trace_id)

        msg_rows: list[TraceStageAttemptRow] = []
        if root_msg and root_msg.direction == direction:
            msg_rows.append(
                TraceStageAttemptRow(
                    trace_id=orig_trace_id,
                    status=root_msg.status.value if root_msg.status else "UNKNOWN",
                    primary_layer="EDI_MESSAGE",
                    created_at=root_msg.created_at.isoformat() if root_msg.created_at else None,
                    replay_count=root_msg.replay_count,
                    parent_trace_id=root_msg.parent_trace_id,
                    original_trace_id=root_msg.original_trace_id,
                )
            )
        for m in lineage_msgs:
            msg_rows.append(
                TraceStageAttemptRow(
                    trace_id=m.trace_id,
                    status=m.status,
                    primary_layer="EDI_MESSAGE",
                    created_at=m.created_at.isoformat() if m.created_at else None,
                    replay_count=m.replay_count,
                    parent_trace_id=m.parent_trace_id,
                    original_trace_id=m.original_trace_id,
                )
            )

        json_rows: list[TraceStageAttemptRow] = []
        if root_json and root_json.direction == direction:
            json_rows.append(
                TraceStageAttemptRow(
                    trace_id=orig_trace_id,
                    status=root_json.status.value if root_json.status else "UNKNOWN",
                    primary_layer="EDI_JSON",
                    created_at=root_json.created_at.isoformat() if root_json.created_at else None,
                    replay_count=root_json.replay_count,
                    parent_trace_id=root_json.parent_trace_id,
                    original_trace_id=root_json.original_trace_id,
                )
            )
        for j in lineage_jsons:
            json_rows.append(
                TraceStageAttemptRow(
                    trace_id=j.trace_id,
                    status=j.status,
                    primary_layer="EDI_JSON",
                    created_at=j.created_at.isoformat() if j.created_at else None,
                    replay_count=j.replay_count,
                    parent_trace_id=j.parent_trace_id,
                    original_trace_id=j.original_trace_id,
                )
            )

        stage_batches = (
            (msg_rows, json_rows) if direction == EdiDirection.INBOUND else (json_rows, msg_rows)
        )
        items = aggregate_trace_lineage_attempts(
            stage_batches_in_pipeline_order=stage_batches,
            fallback_root_trace_id=orig_trace_id,
        )
        items.sort(key=lambda x: (x.replay_count, str(x.created_at or "")))
        return items
