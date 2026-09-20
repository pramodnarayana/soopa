import asyncio

import structlog
from seedwork import generate_id
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix

from edi.domain.enums import MessageStatus, TraceEventType
from edi.domain.events import DeliverRequestedEvent, TransformRequestedEvent
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.transactions import EdiMessageDomainModel, TraceEventDomainModel
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class BulkReplayTransactionsUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def bulk_retry_transform(
        self,
        tenant_id: str,
        trace_ids: list[str],
        actor: str,
        command_key: str | None = None,
    ) -> int:
        """
        Immutable bulk replay — TRANSFORM checkpoint.

        For each original trace_id, creates a brand-new EdiMessage aggregate with a
        fresh trace_id, parent_trace_id=<original>, original_trace_id=<root ancestor>.
        Persistence is driven exclusively through save_all() — no dual-writes.
        The original records are NEVER mutated.
        """
        originals = await self.uow.transactions.get_edi_messages_by_traces(trace_ids)
        if len(originals) != len(trace_ids):
            raise TransactionNotFoundError(trace_id="Multiple")

        logger.info(
            "bulk_replay_transform.started",
            tenant_id=tenant_id,
            count=len(trace_ids),
            actor=actor,
        )

        new_aggregates: list[EdiMessageDomainModel] = []
        audit_events: list[TraceEventDomainModel] = []

        for i, original in enumerate(originals):
            root_trace_id = original.original_trace_id or original.trace_id
            new_trace_id = generate_id(SystemIdPrefix.TRACE)
            idempotency_key = f"{command_key}_{i}" if command_key else new_trace_id

            new_edi_message = EdiMessageDomainModel(
                id=generate_id(DomainIdPrefix.EDI_MESSAGE),
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                direction=original.direction,
                status=MessageStatus.RECEIVED,
                parent_trace_id=original.trace_id,
                original_trace_id=root_trace_id,
                is_replay=True,
                connection_type=original.connection_type,
                sender_id=original.sender_id,
                receiver_id=original.receiver_id,
                as2_sender_id=original.as2_sender_id,
                as2_receiver_id=original.as2_receiver_id,
                gs_sender_id=original.gs_sender_id,
                gs_receiver_id=original.gs_receiver_id,
                trading_partner_id=original.trading_partner_id,
                transaction_type=original.transaction_type,
                format_standard=original.format_standard,
                edi_data=original.edi_data,
                storage_uri=original.storage_uri,
            )

            transform_event = TransformRequestedEvent(
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                trading_partner_id=original.trading_partner_id,
                sender_id=original.sender_id,
                receiver_id=original.receiver_id,
                direction=str(original.direction.value) if original.direction else None,
                edi_message_id=new_edi_message.id,
                idempotency_key=idempotency_key,
            )
            new_edi_message.add_domain_event(transform_event)
            new_aggregates.append(new_edi_message)

            audit_events.append(
                TraceEventDomainModel(
                    id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
                    tenant_id=tenant_id,
                    trace_id=original.trace_id,
                    event_type=TraceEventType.REPLAY_TRANSFORM.value,
                    actor=actor,
                    metadata={"replay_trace_id": new_trace_id},
                )
            )

            await asyncio.sleep(0)  # Yield to event loop between iterations

        await self.uow.transactions.save_all(new_aggregates)
        await self.uow.transactions.save_all_trace_events(audit_events)
        await self.uow.commit()

        processed_count = len(new_aggregates)
        logger.info(
            "bulk_replay_transform.completed",
            tenant_id=tenant_id,
            processed_count=processed_count,
        )
        return processed_count

    async def bulk_retry_deliver(
        self,
        tenant_id: str,
        trace_ids: list[str],
        actor: str,
        command_key: str | None = None,
    ) -> int:
        """
        Immutable bulk replay — DELIVERY checkpoint.

        For each original trace_id, creates a brand-new EdiMessage aggregate in
        TRANSFORMED state with a fresh trace_id, emitting a DeliverRequestedEvent.
        Persistence is driven exclusively through save_all() — no dual-writes.
        The original records are NEVER mutated.
        """
        originals = await self.uow.transactions.get_edi_messages_by_traces(trace_ids)
        if len(originals) != len(trace_ids):
            raise TransactionNotFoundError(trace_id="Multiple")

        logger.info(
            "bulk_replay_deliver.started",
            tenant_id=tenant_id,
            count=len(trace_ids),
            actor=actor,
        )

        new_aggregates: list[EdiMessageDomainModel] = []
        audit_events: list[TraceEventDomainModel] = []

        for i, original in enumerate(originals):
            root_trace_id = original.original_trace_id or original.trace_id
            new_trace_id = generate_id(SystemIdPrefix.TRACE)
            idempotency_key = f"{command_key}_{i}" if command_key else new_trace_id

            new_edi_message = EdiMessageDomainModel(
                id=generate_id(DomainIdPrefix.EDI_MESSAGE),
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                direction=original.direction,
                status=MessageStatus.TRANSFORMED,
                parent_trace_id=original.trace_id,
                original_trace_id=root_trace_id,
                is_replay=True,
                connection_type=original.connection_type,
                sender_id=original.sender_id,
                receiver_id=original.receiver_id,
                as2_sender_id=original.as2_sender_id,
                as2_receiver_id=original.as2_receiver_id,
                gs_sender_id=original.gs_sender_id,
                gs_receiver_id=original.gs_receiver_id,
                trading_partner_id=original.trading_partner_id,
                transaction_type=original.transaction_type,
                format_standard=original.format_standard,
                edi_data=original.edi_data,
                storage_uri=original.storage_uri,
            )

            deliver_event = DeliverRequestedEvent(
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                trading_partner_id=original.trading_partner_id,
                transaction_type=original.transaction_type,
                direction=str(original.direction.value) if original.direction else None,
                idempotency_key=idempotency_key,
            )
            new_edi_message.add_domain_event(deliver_event)
            new_aggregates.append(new_edi_message)

            audit_events.append(
                TraceEventDomainModel(
                    id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
                    tenant_id=tenant_id,
                    trace_id=original.trace_id,
                    event_type=TraceEventType.REPLAY_DELIVER.value,
                    actor=actor,
                    metadata={"replay_trace_id": new_trace_id},
                )
            )

            await asyncio.sleep(0)  # Yield to event loop between iterations

        await self.uow.transactions.save_all(new_aggregates)
        await self.uow.transactions.save_all_trace_events(audit_events)
        await self.uow.commit()

        processed_count = len(new_aggregates)
        logger.info(
            "bulk_replay_deliver.completed",
            tenant_id=tenant_id,
            processed_count=processed_count,
        )
        return processed_count
