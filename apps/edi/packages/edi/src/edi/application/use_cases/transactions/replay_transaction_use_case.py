from seedwork import generate_id

from edi.domain.enums import TraceEventType
from edi.domain.events import DeliverRequestedEvent, TransformRequestedEvent
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.transactions import TraceEventDomainModel
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class ReplayTransactionUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def retry_transform(self, tenant_id: str, trace_id: str, actor: str) -> None:
        """
        Trigger a replay of the transform pipeline.
        Updates state to indicate replay and emits a TRANSFORMATION_REQUESTED.
        """
        edi_message = await self.uow.transactions.get_edi_message(trace_id)
        if not edi_message:
            raise TransactionNotFoundError(trace_id=trace_id)

        # Update state
        edi_message.is_replay = True
        # Emit Pipeline Event
        transform_event = TransformRequestedEvent(
            trace_id=trace_id,
            tenant_id=tenant_id,
            trading_partner_id=edi_message.trading_partner_id,
            sender_id=edi_message.sender_id,
            receiver_id=edi_message.receiver_id,
            direction=edi_message.direction,
            edi_message_id=edi_message.id,
            status=edi_message.status,
        )
        edi_message.add_domain_event(transform_event)

        await self.uow.transactions.save(edi_message)

        # Emit Audit Ledger Event
        trace_event = TraceEventDomainModel(
            id=generate_id("trace_evt"),
            tenant_id=tenant_id,
            trace_id=trace_id,
            event_type=TraceEventType.REPLAY_TRANSFORM.value,
            actor=actor,
        )
        await self.uow.transactions.save_trace_event(trace_event)

        await self.uow.commit()

    async def retry_deliver(self, tenant_id: str, trace_id: str, actor: str) -> None:
        """
        Trigger a replay of the delivery pipeline.
        Updates state to indicate replay and emits a DELIVERY_REQUESTED.
        """
        # We need either an EdiMessage or EdiJson to attach the domain event
        # Let's get the trace composite to figure out what we have
        trace_dto = await self.uow.traces.get_edi_trace(tenant_id, trace_id)
        if not trace_dto or not trace_dto.edi_message:
            raise TransactionNotFoundError(trace_id=trace_id)

        msg_dto = trace_dto.edi_message

        edi_message = await self.uow.transactions.get_edi_message(trace_id)
        if not edi_message:
            raise TransactionNotFoundError(trace_id=trace_id)

        # Update state
        edi_message.is_replay = True
        # Emit Pipeline Event
        deliver_event = DeliverRequestedEvent(
            trace_id=trace_id,
            tenant_id=tenant_id,
            trading_partner_id=msg_dto.trading_partner_id,
            transaction_type=msg_dto.transaction_type,
            direction=msg_dto.direction,
        )
        edi_message.add_domain_event(deliver_event)

        await self.uow.transactions.save(edi_message)

        # Emit Audit Ledger Event
        trace_event = TraceEventDomainModel(
            id=generate_id("trace_evt"),
            tenant_id=tenant_id,
            trace_id=trace_id,
            event_type=TraceEventType.REPLAY_DELIVER.value,
            actor=actor,
        )
        await self.uow.transactions.save_trace_event(trace_event)

        await self.uow.commit()
