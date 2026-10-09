import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork import generate_id
from seedwork.id_registry import DomainIdPrefix

from edi.domain.enums import EdiDirection, TraceEventType, TransactionEntityType
from edi.domain.events import DeliverRequestedEvent, TransformRequestedEvent
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.transactions import (
    TraceEventDomainModel,
)
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class ReplayTransactionUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort, publisher: OutboxPublisherPort) -> None:
        self.uow = uow
        self.publisher = publisher

    async def retry_transform(self, tenant_id: str, trace_id: str, actor: str) -> str:
        """
        Immutable Replay — TRANSFORM checkpoint.
        """
        original_msg = await self.uow.transactions.get_edi_message(trace_id)
        original_json = await self.uow.transactions.get_edi_json(trace_id)

        logger.info(
            "replay_transform.lookup",
            tenant_id=tenant_id,
            trace_id=trace_id,
            found_msg=original_msg is not None,
            found_json=original_json is not None,
        )

        if not original_msg and not original_json:
            raise TransactionNotFoundError(trace_id=trace_id)

        # For INBOUND, edi_message is the root. For OUTBOUND, edi_json is the root.
        direction = (
            original_msg.direction
            if original_msg
            else (original_json.direction if original_json else None)
        )

        logger.info(
            "replay_transform.started",
            tenant_id=tenant_id,
            trace_id=trace_id,
            actor=actor,
            direction=str(direction.value) if direction else None,
        )

        if direction == EdiDirection.INBOUND:
            if not original_msg:
                raise TransactionNotFoundError(trace_id=trace_id)
            transform_event = TransformRequestedEvent(
                trace_id=trace_id,
                tenant_id=tenant_id,
                trading_partner_id=original_msg.trading_partner_id,
                sender_id=original_msg.sender_id,
                receiver_id=original_msg.receiver_id,
                direction=str(original_msg.direction.value) if original_msg.direction else None,
                edi_message_id=original_msg.id,
            )
            original_msg.add_domain_event(transform_event)
            envelopes = await self.uow.transactions.flush_events(original_msg)

        elif direction == EdiDirection.OUTBOUND:
            if not original_json:
                raise TransactionNotFoundError(trace_id=trace_id)
            transform_event = TransformRequestedEvent(
                trace_id=trace_id,
                tenant_id=tenant_id,
                trading_partner_id=original_json.trading_partner_id,
                direction=str(original_json.direction.value) if original_json.direction else None,
            )
            original_json.add_domain_event(transform_event)
            envelopes = await self.uow.transactions.save_json(original_json)

        audit_event = TraceEventDomainModel(
            id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
            tenant_id=tenant_id,
            trace_id=trace_id,
            event_type=TraceEventType.REPLAY_TRANSFORM.value,
            actor=actor,
        )
        await self.uow.transactions.save_trace_event(audit_event)

        logger.info(
            "replay_transform.pre_commit",
            tenant_id=tenant_id,
            trace_id=trace_id,
            direction=str(direction.value) if direction else None,
        )
        entity_types = (
            [TransactionEntityType.EDI_MESSAGE, TransactionEntityType.EDI_JSON]
            if direction == EdiDirection.INBOUND
            else [TransactionEntityType.EDI_JSON, TransactionEntityType.EDI_MESSAGE]
        )
        await self.uow.transactions.increment_replay_count(tenant_id, [trace_id], entity_types)
        await self.uow.commit()
        for env in envelopes:
            await self.publisher.publish(env)
            # Outbox marks as completed in the same transaction loop? No, Sweeper handles failure
            await self.uow.outbox.mark_completed(env.id)
        logger.info(
            "replay_transform.completed",
            tenant_id=tenant_id,
            trace_id=trace_id,
        )
        return trace_id

    async def retry_deliver(self, tenant_id: str, trace_id: str, actor: str) -> str:
        """
        Immutable Replay — DELIVERY checkpoint.
        """
        original = await self.uow.transactions.get_edi_message(trace_id)
        if not original:
            raise TransactionNotFoundError(trace_id=trace_id)

        logger.info(
            "replay_deliver.started",
            tenant_id=tenant_id,
            trace_id=trace_id,
            actor=actor,
        )

        deliver_event = DeliverRequestedEvent(
            trace_id=trace_id,
            tenant_id=tenant_id,
            trading_partner_id=original.trading_partner_id,
            transaction_type=original.transaction_type,
            direction=str(original.direction.value) if original.direction else None,
        )
        original.add_domain_event(deliver_event)
        envelopes = await self.uow.transactions.flush_events(original)

        audit_event = TraceEventDomainModel(
            id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
            tenant_id=tenant_id,
            trace_id=trace_id,
            event_type=TraceEventType.REPLAY_DELIVER.value,
            actor=actor,
        )
        await self.uow.transactions.save_trace_event(audit_event)

        entity_types = (
            [TransactionEntityType.EDI_JSON]
            if original.direction == EdiDirection.INBOUND
            else [TransactionEntityType.EDI_MESSAGE]
        )
        await self.uow.transactions.increment_replay_count(tenant_id, [trace_id], entity_types)
        await self.uow.commit()
        for env in envelopes:
            await self.publisher.publish(env)
            # Outbox marks as completed in the same transaction loop? No, Sweeper handles failure
            await self.uow.outbox.mark_completed(env.id)

        logger.info(
            "replay_deliver.completed",
            tenant_id=tenant_id,
            trace_id=trace_id,
        )
        return trace_id
