"""Use case for dispatching a canonical event to matching Stitches on the tenant Data Plane shard."""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventResultDTO,
)
from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.exceptions import IpError, Result
from ip.engine.ports.outbound.stitch_catalog_registry_port import StitchShardGatewayPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class TriggerStitchEventCommand:
    """Command to dispatch a canonical event to matching Stitches on the tenant shard."""

    tenant_id: str
    canonical_event_type: str
    payload: JsonDict
    event_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None


class TriggerStitchEventUseCase:
    """Dispatches a canonical event to matching Stitches on the tenant Data Plane shard."""

    def __init__(self, *, shard_gateway: StitchShardGatewayPort) -> None:
        self._shard_gateway = shard_gateway

    async def execute(
        self, command: TriggerStitchEventCommand
    ) -> Result[DispatchCanonicalEventResultDTO, IpError]:
        trace_id = (
            command.trace_id.strip()
            if command.trace_id and command.trace_id.strip()
            else generate_id(IpIdPrefix.TRACE.value)
        )
        event_id = (
            command.event_id.strip()
            if command.event_id and command.event_id.strip()
            else generate_id(SystemIdPrefix.IDEMPOTENCY.value)
        )
        bound = logger.bind(
            tenant_id=command.tenant_id,
            canonical_event_type=command.canonical_event_type,
            event_id=event_id,
            trace_id=trace_id,
        )
        bound.info("trigger_stitch_event.received")

        res = await self._shard_gateway.dispatch_event(
            tenant_id=command.tenant_id,
            canonical_event_type=command.canonical_event_type,
            event_id=event_id,
            payload=command.payload,
            trace_id=trace_id,
            correlation_id=command.correlation_id,
        )
        if res.is_err:
            err = res.unwrap_err()
            bound.error(
                "trigger_stitch_event.failed",
                error_code=err.code.value,
                error=err.message,
            )
            return Result.err(err)

        started, deduped, signalled = res.unwrap()
        bound.info(
            "trigger_stitch_event.completed",
            started_count=len(started),
            deduplicated_count=len(deduped),
            signalled_count=len(signalled),
        )
        return Result.ok(
            DispatchCanonicalEventResultDTO(
                started_run_ids=started,
                deduplicated_run_ids=deduped,
                signalled_step_ids=signalled,
            )
        )


__all__ = [
    "TriggerStitchEventCommand",
    "TriggerStitchEventUseCase",
]
