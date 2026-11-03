from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from seedwork.events import EventEnvelope

from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import MessageStatus
from edi.domain.transaction.stage_filter import StageFilterCriterion


class EdiMessageRepositoryPort(Protocol):
    """Port for the Data-Plane EdiMessage stage aggregate repository."""

    async def get_edi_message(
        self, trace_id: str, tenant_id: str | None = None
    ) -> EdiMessage | None: ...

    async def get_edi_messages_by_traces(
        self, tenant_id: str, trace_ids: Sequence[str]
    ) -> Sequence[EdiMessage]: ...

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int = 50,
        offset: int = 0,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> Sequence[EdiMessage]: ...

    async def explorer_list_edi_messages(
        self,
        tenant_id: str,
        filters: Sequence[StageFilterCriterion],
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[EdiMessage]: ...

    async def save(self, aggregate: EdiMessage) -> Sequence[EventEnvelope]: ...

    async def save_all(self, aggregates: Sequence[EdiMessage]) -> Sequence[EventEnvelope]: ...

    async def flush_events(self, aggregate: EdiMessage) -> Sequence[EventEnvelope]: ...

    async def update_edi_message_metadata(
        self,
        trace_id: str,
        gs_sender_id: str | None,
        gs_receiver_id: str | None,
        transaction_type: str | None,
    ) -> None: ...

    async def update_edi_message_status(self, trace_id: str, status: MessageStatus) -> None: ...

    async def update_outbound_delivery_metadata(self, aggregate: EdiMessage) -> None: ...

    async def increment_replay_count(self, tenant_id: str, trace_ids: Sequence[str]) -> None: ...


__all__ = [
    "EdiMessageRepositoryPort",
]
