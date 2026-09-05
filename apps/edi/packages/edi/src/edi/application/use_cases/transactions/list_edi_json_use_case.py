from collections.abc import Sequence

from edi.application.dtos.transactions import EdiJsonDTO
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class ListEdiJsonUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def list_edi_json(self, tenant_id: str, key: str, value: str) -> Sequence[EdiJsonDTO]:
        """
        List all EDI JSON records (Tab 2 in UI).
        """
        return await self.uow.transactions.list_edi_json(tenant_id, key, value)
