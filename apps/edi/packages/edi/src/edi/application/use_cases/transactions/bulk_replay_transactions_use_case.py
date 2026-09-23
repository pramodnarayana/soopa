import asyncio

import structlog
from seedwork import generate_id
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix

from edi.domain.enums import TraceEventType, TransactionEntityType
from edi.domain.events import DeliverRequestedEvent, TransformRequestedEvent
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.transactions import TraceEventDomainModel
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

        Using the pure correlation ID approach, this does NOT create new EdiMessage models.
        It appends domain events (TransformRequestedEvent) to the existing aggregates.
        """
        unique_trace_ids = list(dict.fromkeys(trace_ids))

        try:
            originals = await self.uow.transactions.get_edi_messages_by_traces(
                tenant_id, unique_trace_ids
            )
        except ValueError as e:
            raise TransactionNotFoundError(trace_id="Multiple") from e

        if len(originals) != len(unique_trace_ids):
            raise TransactionNotFoundError(trace_id="Multiple")

        logger.info(
            "bulk_replay_transform.started",
            tenant_id=tenant_id,
            count=len(trace_ids),
            actor=actor,
        )

        audit_events: list[TraceEventDomainModel] = []

        for i, original in enumerate(originals):
            idempotency_key = (
                f"{command_key}_{i}" if command_key else generate_id(SystemIdPrefix.IDEMPOTENCY)
            )

            if original.direction and str(original.direction.value) == "INBOUND":
                transform_event = TransformRequestedEvent(
                    trace_id=original.trace_id,
                    tenant_id=tenant_id,
                    trading_partner_id=original.trading_partner_id,
                    sender_id=original.sender_id,
                    receiver_id=original.receiver_id,
                    direction=str(original.direction.value) if original.direction else None,
                    edi_message_id=original.id,
                    idempotency_key=idempotency_key,
                )
                original.add_domain_event(transform_event)

            audit_events.append(
                TraceEventDomainModel(
                    id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
                    tenant_id=tenant_id,
                    trace_id=original.trace_id,
                    event_type=TraceEventType.REPLAY_TRANSFORM.value,
                    actor=actor,
                    metadata={"replay_type": "transform"},
                )
            )

            await asyncio.sleep(0)  # Yield to event loop between iterations

        await self.uow.transactions.save_all(list(originals))
        await self.uow.transactions.save_all_trace_events(audit_events)
        await self.uow.transactions.increment_replay_count(
            tenant_id,
            unique_trace_ids,
            [TransactionEntityType.EDI_MESSAGE, TransactionEntityType.EDI_JSON],
        )
        await self.uow.commit()

        processed_count = len(originals)
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

        Using the pure correlation ID approach, this does NOT create new EdiMessage models.
        It updates the status to TRANSFORMED and appends DeliverRequestedEvent.
        """
        unique_trace_ids = list(dict.fromkeys(trace_ids))

        try:
            originals = await self.uow.transactions.get_edi_messages_by_traces(
                tenant_id, unique_trace_ids
            )
        except ValueError as e:
            raise TransactionNotFoundError(trace_id="Multiple") from e

        if len(originals) != len(unique_trace_ids):
            raise TransactionNotFoundError(trace_id="Multiple")

        logger.info(
            "bulk_replay_deliver.started",
            tenant_id=tenant_id,
            count=len(trace_ids),
            actor=actor,
        )

        audit_events: list[TraceEventDomainModel] = []

        for i, original in enumerate(originals):
            idempotency_key = (
                f"{command_key}_{i}" if command_key else generate_id(SystemIdPrefix.IDEMPOTENCY)
            )

            deliver_event = DeliverRequestedEvent(
                trace_id=original.trace_id,
                tenant_id=tenant_id,
                trading_partner_id=original.trading_partner_id,
                transaction_type=original.transaction_type,
                direction=str(original.direction.value) if original.direction else None,
                idempotency_key=idempotency_key,
            )
            original.add_domain_event(deliver_event)

            audit_events.append(
                TraceEventDomainModel(
                    id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
                    tenant_id=tenant_id,
                    trace_id=original.trace_id,
                    event_type=TraceEventType.REPLAY_DELIVER.value,
                    actor=actor,
                    metadata={"replay_type": "deliver"},
                )
            )

            await asyncio.sleep(0)

        await self.uow.transactions.save_all(list(originals))
        await self.uow.transactions.save_all_trace_events(audit_events)
        await self.uow.transactions.increment_replay_count(
            tenant_id, unique_trace_ids, [TransactionEntityType.EDI_MESSAGE]
        )
        await self.uow.commit()

        processed_count = len(originals)
        logger.info(
            "bulk_replay_deliver.completed",
            tenant_id=tenant_id,
            processed_count=processed_count,
        )
        return processed_count
