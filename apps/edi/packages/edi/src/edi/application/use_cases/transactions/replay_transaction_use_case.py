import structlog
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
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def retry_transform(self, tenant_id: str, trace_id: str, actor: str) -> str:
        """
        Immutable Replay — TRANSFORM checkpoint.
        """
        original = await self.uow.transactions.get_edi_message(trace_id)
        logger.info(
            "replay_transform.lookup_edi_message",
            tenant_id=tenant_id,
            trace_id=trace_id,
            found=original is not None,
            direction=str(original.direction.value) if (original and original.direction) else None,
        )
        if not original:
            raise TransactionNotFoundError(trace_id=trace_id)

        logger.info(
            "replay_transform.started",
            tenant_id=tenant_id,
            trace_id=trace_id,
            actor=actor,
        )

        if original.direction == EdiDirection.INBOUND:
            transform_event = TransformRequestedEvent(
                trace_id=trace_id,
                tenant_id=tenant_id,
                trading_partner_id=original.trading_partner_id,
                sender_id=original.sender_id,
                receiver_id=original.receiver_id,
                direction=str(original.direction.value) if original.direction else None,
                edi_message_id=original.id,
            )
            original.add_domain_event(transform_event)
            await self.uow.transactions.save(original)

        elif original.direction == EdiDirection.OUTBOUND:
            original_json = await self.uow.transactions.get_edi_json(trace_id)
            logger.info(
                "replay_transform.lookup_edi_json",
                tenant_id=tenant_id,
                trace_id=trace_id,
                found=original_json is not None,
                transaction_type=original_json.transaction_type if original_json else None,
            )
            if not original_json:
                raise TransactionNotFoundError(trace_id=trace_id)
            transform_event = TransformRequestedEvent(
                trace_id=trace_id,
                tenant_id=tenant_id,
                trading_partner_id=original.trading_partner_id,
                direction=str(original.direction.value) if original.direction else None,
            )
            original_json.add_domain_event(transform_event)
            await self.uow.transactions.save_json(original_json)

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
            direction=str(original.direction.value) if original.direction else None,
        )
        entity_types = (
            [TransactionEntityType.EDI_MESSAGE, TransactionEntityType.EDI_JSON]
            if original.direction == EdiDirection.INBOUND
            else [TransactionEntityType.EDI_JSON, TransactionEntityType.EDI_MESSAGE]
        )
        await self.uow.transactions.increment_replay_count(tenant_id, [trace_id], entity_types)
        await self.uow.commit()
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
        await self.uow.transactions.save(original)

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

        logger.info(
            "replay_deliver.completed",
            tenant_id=tenant_id,
            trace_id=trace_id,
        )
        return trace_id
