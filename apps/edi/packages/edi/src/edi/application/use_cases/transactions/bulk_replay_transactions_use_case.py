from seedwork import generate_random_hex

from edi.domain.exceptions import TransactionNotFoundError
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class BulkReplayTransactionsUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def bulk_replay_transactions(
        self, tenant_id: str, trace_ids: list[str], tier: str, command_key: str | None = None
    ) -> int:
        """
        Trigger an asynchronous replay of multiple transactions at the specified tier.
        """
        processed_count = 0
        batch_id = command_key or generate_random_hex(6)

        for i, trace_id in enumerate(trace_ids):
            result = await self.uow.transactions.get_transaction(tenant_id, trace_id)
            if not result or not result.edi_message:
                raise TransactionNotFoundError(trace_id=trace_id)

            await self.uow.transactions.publish_outbox_event(
                tenant_id=tenant_id,
                event_type="edi.transaction.replay_requested",
                payload={"trace_id": trace_id, "tier": tier},
                idempotency_key=f"bulk_replay_{batch_id}_{i}",
            )
            processed_count += 1

        return processed_count
