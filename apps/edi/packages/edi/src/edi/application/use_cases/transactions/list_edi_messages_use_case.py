from collections.abc import Sequence

from edi.application.dtos.transactions import EdiMessageDTO
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class ListEdiMessagesUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def list_edi_messages(
        self,
        tenant_id: str,
        limit: int,
        offset: int,
        partner_id: str | None = None,
        transaction_type: str | None = None,
        direction: str | None = None,
    ) -> Sequence[EdiMessageDTO]:
        """
        List all EDI Messages (Tab 1 in UI).
        """
        return await self.uow.transactions.list_edi_messages(
            tenant_id,
            limit=limit,
            offset=offset,
            partner_id=partner_id,
            transaction_type=transaction_type,
            direction=direction,
        )
