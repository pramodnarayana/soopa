from edi.domain.constants import TransactionStatus
from edi.domain.models import TransactionListDomainModel
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class ListTransactionsUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def list_transactions(
        self, tenant_id: str, skip: int, limit: int
    ) -> list[TransactionListDomainModel]:
        """
        List all transactions (high-level view for data plane).
        """
        messages = await self.uow.transactions.list_transactions(
            tenant_id, limit=limit, offset=skip
        )
        return [
            TransactionListDomainModel(
                trace_id=m.trace_id,
                transaction_type=m.transaction_type,
                direction=m.direction,
                trading_partner_id=m.trading_partner_id,
                status=TransactionStatus.UNKNOWN.value,  # Simplified for the list view
                received_at=m.received_at.isoformat(),
            )
            for m in messages
        ]
