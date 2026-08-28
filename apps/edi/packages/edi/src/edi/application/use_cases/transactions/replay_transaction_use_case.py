import uuid

from edi.domain.exceptions import TransactionNotFoundError
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class ReplayTransactionUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def replay_transaction(self, tenant_id: str, trace_id: str, tier: str) -> None:
        """
        Trigger an asynchronous replay of a transaction at the specified tier.
        Publishes an outbox event.
        """
        # Validate existence
        result = await self.uow.transactions.get_transaction(tenant_id, trace_id)
        if not result or not result.edi_message:
            raise TransactionNotFoundError(trace_id=trace_id)

        await self.uow.transactions.publish_outbox_event(
            tenant_id=tenant_id,
            event_type="edi.transaction.replay_requested",
            payload={"trace_id": trace_id, "tier": tier},
            idempotency_key=f"replay_{trace_id}_{uuid.uuid4().hex}",
        )
