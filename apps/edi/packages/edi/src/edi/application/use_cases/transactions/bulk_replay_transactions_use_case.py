import asyncio

from seedwork import generate_id

from edi.domain.enums import TraceEventType
from edi.domain.events import DeliverRequestedEvent, TransformRequestedEvent
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.transactions import TraceEventDomainModel
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort


class BulkReplayTransactionsUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def bulk_retry_transform(
        self, tenant_id: str, trace_ids: list[str], actor: str, command_key: str | None = None
    ) -> int:
        """
        Trigger an asynchronous replay of the transform pipeline for multiple transactions.
        """
        edi_messages = await self.uow.transactions.get_edi_messages_by_traces(trace_ids)
        if len(edi_messages) != len(trace_ids):
            raise TransactionNotFoundError(trace_id="Multiple")

        trace_events = []
        processed_count = 0

        for i, edi_message in enumerate(edi_messages):
            edi_message.is_replay = True
            if command_key:
                transform_event = TransformRequestedEvent(
                    trace_id=edi_message.trace_id,
                    tenant_id=tenant_id,
                    trading_partner_id=edi_message.trading_partner_id,
                    sender_id=edi_message.sender_id,
                    receiver_id=edi_message.receiver_id,
                    direction=edi_message.direction,
                    edi_message_id=edi_message.id,
                    status=edi_message.status,
                    idempotency_key=f"{command_key}_{i}",
                )
            else:
                transform_event = TransformRequestedEvent(
                    trace_id=edi_message.trace_id,
                    tenant_id=tenant_id,
                    trading_partner_id=edi_message.trading_partner_id,
                    sender_id=edi_message.sender_id,
                    receiver_id=edi_message.receiver_id,
                    direction=edi_message.direction,
                    edi_message_id=edi_message.id,
                    status=edi_message.status,
                )
            edi_message.add_domain_event(transform_event)

            trace_events.append(
                TraceEventDomainModel(
                    id=generate_id("trace_evt"),
                    tenant_id=tenant_id,
                    trace_id=edi_message.trace_id,
                    event_type=TraceEventType.REPLAY_TRANSFORM.value,
                    actor=actor,
                )
            )
            processed_count += 1
            await asyncio.sleep(0)  # Yield to event loop

        await self.uow.transactions.save_all(edi_messages)
        await self.uow.transactions.save_all_trace_events(trace_events)
        await self.uow.commit()
        return processed_count

    async def bulk_retry_deliver(
        self, tenant_id: str, trace_ids: list[str], actor: str, command_key: str | None = None
    ) -> int:
        """
        Trigger an asynchronous replay of the delivery pipeline for multiple transactions.
        """
        edi_messages = await self.uow.transactions.get_edi_messages_by_traces(trace_ids)
        if len(edi_messages) != len(trace_ids):
            raise TransactionNotFoundError(trace_id="Multiple")

        trace_events = []
        processed_count = 0

        for i, edi_message in enumerate(edi_messages):
            edi_message.is_replay = True
            if command_key:
                deliver_event = DeliverRequestedEvent(
                    trace_id=edi_message.trace_id,
                    tenant_id=tenant_id,
                    idempotency_key=f"{command_key}_{i}",
                )
            else:
                deliver_event = DeliverRequestedEvent(
                    trace_id=edi_message.trace_id,
                    tenant_id=tenant_id,
                )
            edi_message.add_domain_event(deliver_event)

            trace_events.append(
                TraceEventDomainModel(
                    id=generate_id("trace_evt"),
                    tenant_id=tenant_id,
                    trace_id=edi_message.trace_id,
                    event_type=TraceEventType.REPLAY_DELIVER.value,
                    actor=actor,
                )
            )
            processed_count += 1
            await asyncio.sleep(0)  # Yield to event loop

        await self.uow.transactions.save_all(edi_messages)
        await self.uow.transactions.save_all_trace_events(trace_events)
        await self.uow.commit()
        return processed_count
