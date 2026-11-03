from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from edi.application.responses import EdiMessageDTO
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


@dataclass(frozen=True, kw_only=True)
class ListEdiMessagesQuery:
    tenant_id: str
    limit: int = 50
    offset: int = 0
    partner_id: str | None = None
    transaction_type: str | None = None
    direction: str | None = None


class ListEdiMessagesUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, query: ListEdiMessagesQuery) -> Sequence[EdiMessageDTO]:
        """List EDI Messages (Tab 1 in UI)."""
        messages = await self._uow.edi_messages.list_edi_messages(
            query.tenant_id,
            limit=query.limit,
            offset=query.offset,
            partner_id=query.partner_id,
            transaction_type=query.transaction_type,
            direction=query.direction,
        )
        return [EdiMessageDTO.from_domain(msg) for msg in messages]
