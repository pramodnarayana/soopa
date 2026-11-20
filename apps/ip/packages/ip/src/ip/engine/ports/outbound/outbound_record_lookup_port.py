"""Interface-segregated port for looking up an L5 OutboundRecord by idempotency key."""

from __future__ import annotations

from typing import Protocol

from ip.engine.domain.dispatch.outbound_record import OutboundRecord


class OutboundRecordLookupPort(Protocol):
    """Interface-segregated port for looking up an L5 OutboundRecord by idempotency key."""

    async def get_by_idempotency_key(
        self,
        tenant_id: str,
        connection_id: str,
        idempotency_key: str,
    ) -> OutboundRecord | None: ...
