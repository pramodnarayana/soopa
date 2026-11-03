from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from seedwork.events import EventEnvelope

from edi.domain.transaction.edi_json import EdiJson
from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.stage_filter import StageFilterCriterion


class EdiJsonRepositoryPort(Protocol):
    """Port for the Data-Plane EdiJson stage aggregate repository."""

    async def get_edi_json(self, trace_id: str, tenant_id: str | None = None) -> EdiJson | None: ...

    async def get_edi_jsons_by_trace_id(
        self, trace_id: str, tenant_id: str | None = None
    ) -> list[EdiJson]: ...

    async def get_edi_json_by_idempotency_key(
        self, tenant_id: str, idempotency_key: str
    ) -> EdiJson | None: ...

    async def list_edi_json(self, tenant_id: str, key: str, value: str) -> Sequence[EdiJson]: ...

    async def explorer_list_edi_json(
        self,
        tenant_id: str,
        filters: Sequence[StageFilterCriterion],
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EdiJson]: ...

    async def save(self, aggregate: EdiJson) -> Sequence[EventEnvelope]: ...

    async def flush_events(self, aggregate: EdiJson) -> Sequence[EventEnvelope]: ...

    async def update_edi_json_routing_metadata(
        self,
        trace_id: str,
        *,
        trading_partner_id: str | None = None,
        standard: str | None = None,
    ) -> None: ...

    async def update_edi_json_status(self, trace_id: str, status: MessageStatus) -> None: ...

    async def increment_replay_count(self, tenant_id: str, trace_ids: Sequence[str]) -> None: ...


__all__ = [
    "EdiJsonRepositoryPort",
]
