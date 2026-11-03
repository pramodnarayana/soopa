from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from edi.application.responses import EdiJsonDTO
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


@dataclass(frozen=True, kw_only=True)
class ListEdiJsonQuery:
    tenant_id: str
    key: str
    value: str


class ListEdiJsonUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(self, query: ListEdiJsonQuery) -> Sequence[EdiJsonDTO]:
        """List EDI JSON records matching a business metadata key/value (Tab 2 in UI)."""
        records = await self._uow.edi_jsons.list_edi_json(query.tenant_id, query.key, query.value)
        return [EdiJsonDTO.from_domain(record) for record in records]
