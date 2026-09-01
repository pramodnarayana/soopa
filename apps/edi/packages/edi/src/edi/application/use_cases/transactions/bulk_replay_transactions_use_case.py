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

            from edi.domain.events import TransactionReplayRequestedEvent

            replay_event = TransactionReplayRequestedEvent(
                trace_id=trace_id,
                tenant_id=tenant_id,
                tier=tier,
                explicit_idempotency_key=f"bulk_replay_{batch_id}_{i}",
            )

            edi_message = await self.uow.transactions.get_edi_message(trace_id)
            if edi_message:
                edi_message.add_domain_event(replay_event)
                await self.uow.transactions.save(edi_message)
            else:
                from edi.domain.models.base import Direction, RecordStatus
                from edi.domain.models.transactions import EdiJsonDomainModel

                edi_json = EdiJsonDomainModel(
                    id="dummy",
                    tenant_id=tenant_id,
                    trace_id=trace_id,
                    direction=Direction.OUTBOUND,
                    transaction_type="",
                    status=RecordStatus.RECEIVED,
                    business_metadata={},
                    payload={},
                )
                edi_json.add_domain_event(replay_event)
                await self.uow.transactions.save_json(edi_json)
            processed_count += 1

        await self.uow.commit()
        return processed_count
