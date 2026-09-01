from seedwork import generate_random_hex

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

        from edi.domain.events import TransactionReplayRequestedEvent

        replay_event = TransactionReplayRequestedEvent(
            trace_id=trace_id,
            tenant_id=tenant_id,
            tier=tier,
            explicit_idempotency_key=f"replay_{trace_id}_{generate_random_hex(6)}",
        )

        # We assume the result is a TransactionDetailDTO which doesn't have domain_events,
        # so we need to instantiate a domain model just to act as the aggregate for outbox.
        # But wait, replay is on EdiMessage or EdiJson.
        # We can just fetch the EdiMessage and drain on it, since it's the aggregate root for transactions.
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

        await self.uow.commit()
