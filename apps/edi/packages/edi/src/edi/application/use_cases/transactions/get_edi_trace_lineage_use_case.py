from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import structlog
from seedwork.domain.types import JsonDict

from edi.application.dtos.transactions import EdiJsonDTO, EdiMessageDTO, EdiTraceLineageItemDTO
from edi.domain.enums import EdiDirection
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger()


@dataclass
class _TraceAttemptAccumulator:
    trace_id: str
    msg_status: str | None = None
    json_status: str | None = None
    created_at: datetime | None = None
    replay_count: int = 0


class GetEdiTraceLineageUseCase:
    """
    Returns the full lineage of replay attempts for a given trace.
    Finds the root/original trace id and returns all related attempts chronologically.
    """

    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(self, tenant_id: str, trace_id: str) -> Sequence[EdiTraceLineageItemDTO]:
        log = logger.bind(tenant_id=tenant_id, trace_id=trace_id)

        # 1. Resolve current trace to determine root trace id and direction
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

        # 2. Query both tables for attempts sharing this root original_trace_id and matching direction
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

        # 3. Always include Attempt 1 (root_trace_id) even if its original_trace_id was NULL in legacy rows
        attempts_map: dict[str, _TraceAttemptAccumulator] = {}
        await self._resolve_root_attempt(orig_trace_id, direction, attempts_map)

        # Merge message and json attempts
        self._merge_messages(attempts_map, lineage_msgs)
        self._merge_jsons(attempts_map, lineage_jsons)

        # 4. Resolve overall attempt status based on pipeline direction
        return self._build_lineage_dtos(attempts_map, direction)

    async def _resolve_root_attempt(
        self,
        orig_trace_id: str,
        direction: EdiDirection,
        attempts_map: dict[str, _TraceAttemptAccumulator],
    ) -> None:
        root_msg = await self.uow.transactions.get_edi_message(orig_trace_id)
        root_json = await self.uow.transactions.get_edi_json(orig_trace_id)
        if root_msg and root_msg.direction == direction:
            attempts_map[orig_trace_id] = _TraceAttemptAccumulator(
                trace_id=orig_trace_id,
                msg_status=root_msg.status.value if root_msg.status else "UNKNOWN",
                json_status=None,
                created_at=root_msg.created_at,
                replay_count=root_msg.replay_count,
            )
        if root_json and root_json.direction == direction:
            if orig_trace_id not in attempts_map:
                attempts_map[orig_trace_id] = _TraceAttemptAccumulator(
                    trace_id=orig_trace_id,
                    msg_status=None,
                    json_status=root_json.status.value if root_json.status else "UNKNOWN",
                    created_at=root_json.created_at,
                    replay_count=root_json.replay_count,
                )
            else:
                attempts_map[orig_trace_id].json_status = (
                    root_json.status.value if root_json.status else "UNKNOWN"
                )

    def _merge_messages(
        self,
        attempts_map: dict[str, _TraceAttemptAccumulator],
        records: Sequence[EdiMessageDTO],
    ) -> None:
        for r in records:
            tid = r.trace_id
            if tid not in attempts_map:
                attempts_map[tid] = _TraceAttemptAccumulator(
                    trace_id=tid,
                    msg_status=r.status,
                    created_at=r.created_at,
                    replay_count=r.replay_count,
                )
            else:
                attempts_map[tid].msg_status = r.status
                if r.created_at and not attempts_map[tid].created_at:
                    attempts_map[tid].created_at = r.created_at

    def _merge_jsons(
        self,
        attempts_map: dict[str, _TraceAttemptAccumulator],
        records: Sequence[EdiJsonDTO],
    ) -> None:
        for r in records:
            tid = r.trace_id
            if tid not in attempts_map:
                attempts_map[tid] = _TraceAttemptAccumulator(
                    trace_id=tid,
                    json_status=r.status,
                    created_at=r.created_at,
                    replay_count=r.replay_count,
                )
            else:
                attempts_map[tid].json_status = r.status
                if r.created_at and not attempts_map[tid].created_at:
                    attempts_map[tid].created_at = r.created_at

    def _build_lineage_dtos(
        self,
        attempts_map: dict[str, _TraceAttemptAccumulator],
        direction: EdiDirection,
    ) -> list[EdiTraceLineageItemDTO]:
        result_items: list[EdiTraceLineageItemDTO] = []
        for tid, data in attempts_map.items():
            if direction == EdiDirection.INBOUND:
                effective_status = data.json_status or data.msg_status or "UNKNOWN"
            else:
                effective_status = data.msg_status or data.json_status or "UNKNOWN"

            created_at_dt = data.created_at
            created_at_str = created_at_dt.isoformat() if created_at_dt else None

            result_items.append(
                EdiTraceLineageItemDTO(
                    trace_id=tid,
                    status=effective_status,
                    created_at=created_at_str,
                    replay_count=data.replay_count,
                )
            )

        result_items.sort(key=lambda x: (x.replay_count, x.created_at or ""))
        return result_items
