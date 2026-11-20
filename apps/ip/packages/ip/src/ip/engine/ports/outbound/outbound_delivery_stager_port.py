"""Interface-segregated port for staging an L5 OutboundRecord(PENDING) onto the Egress Queue."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from seedwork.domain.types import JsonDict

from ip.engine.domain.constants import DEFAULT_IDEMPOTENCY_HEADER
from ip.engine.domain.dispatch.enums import (
    HttpWriteOperation,
    OutboundConflictStrategy,
    OutboundDispatchStatus,
)
from ip.engine.domain.exceptions import IpError
from ip.engine.domain.exceptions import Result as IpResult


@dataclass(frozen=True)
class StageOutboundDeliveryCommand:
    """Command staging a Layer-5 outbound dispatch onto the Egress Queue."""

    tenant_id: str
    connection_id: str
    stream_name: str
    operation: str = HttpWriteOperation.CREATE.value
    payload: JsonDict = field(default_factory=dict)
    record_id: str | None = None
    idempotency_key: str | None = None
    idempotency_header_name: str = DEFAULT_IDEMPOTENCY_HEADER
    headers: Mapping[str, str] = field(default_factory=dict)
    conflict_strategy: OutboundConflictStrategy = OutboundConflictStrategy.FAIL
    trace_id: str | None = None
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    causation_depth: int = 0


@dataclass(frozen=True)
class StageOutboundDeliveryResponse:
    """Structured result of staging an `OutboundRecord(PENDING)` into `public.ip_outbox`."""

    outbound_record_id: str
    status: OutboundDispatchStatus
    trace_id: str
    idempotency_key: str
    record_id: str
    was_deduplicated: bool = False


class OutboundDeliveryStagerPort(Protocol):
    """Interface-segregated port for staging an L5 OutboundRecord(PENDING) onto the Egress Queue."""

    async def execute(
        self,
        command: StageOutboundDeliveryCommand,
    ) -> IpResult[StageOutboundDeliveryResponse, IpError]: ...


__all__ = [
    "OutboundDeliveryStagerPort",
    "StageOutboundDeliveryCommand",
    "StageOutboundDeliveryResponse",
]
