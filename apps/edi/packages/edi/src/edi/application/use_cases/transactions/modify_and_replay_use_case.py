import json

import structlog
from seedwork import generate_id
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix

from edi.domain.enums import TraceEventType
from edi.domain.events import DeliverRequestedEvent, TransformRequestedEvent
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.base import Direction, RecordStatus
from edi.domain.models.transactions import (
    EdiJsonDomainModel,
    EdiMessageDomainModel,
    TraceEventDomainModel,
)
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class ModifyAndReplayTransactionUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        original_trace_id: str,
        modified_payload: str,
        actor: str,
    ) -> str:
        """
        Scenario B: Manual Intervention (Modify & Resend).
        Creates a new aggregate with a new trace_id, tracks lineage, and injects it into the pipeline.
        """
        # 1. Determine what kind of record the original trace was.
        # We check EdiMessage first, then EdiJson.
        original_msg = await self.uow.transactions.get_edi_message(
            original_trace_id, tenant_id=tenant_id
        )

        new_trace_id = generate_id(SystemIdPrefix.TRACE)

        logger.info(
            "modify_and_replay.started",
            tenant_id=tenant_id,
            original_trace_id=original_trace_id,
            new_trace_id=new_trace_id,
            actor=actor,
        )

        if original_msg:
            return await self._handle_edi_message(
                tenant_id, original_trace_id, new_trace_id, modified_payload, actor, original_msg
            )

        original_json = await self.uow.transactions.get_edi_json(
            original_trace_id, tenant_id=tenant_id
        )
        if original_json:
            return await self._handle_edi_json(
                tenant_id, original_trace_id, new_trace_id, modified_payload, actor, original_json
            )

        raise TransactionNotFoundError(trace_id=original_trace_id)

    async def _handle_edi_message(
        self,
        tenant_id: str,
        original_trace_id: str,
        new_trace_id: str,
        modified_payload: str,
        actor: str,
        original: EdiMessageDomainModel,
    ) -> str:

        root_trace_id = original.original_trace_id or original.trace_id

        new_msg = EdiMessageDomainModel(
            id=generate_id(DomainIdPrefix.EDI_MESSAGE.value),
            tenant_id=tenant_id,
            trace_id=new_trace_id,
            parent_trace_id=original.trace_id,
            original_trace_id=root_trace_id,
            direction=original.direction,
            status=RecordStatus.RECEIVED
            if original.direction == Direction.INBOUND
            else RecordStatus.TRANSFORMED,
            format_standard=original.format_standard,
            transaction_type=original.transaction_type,
            connection_type=original.connection_type,
            sender_id=original.sender_id,
            receiver_id=original.receiver_id,
            gs_sender_id=original.gs_sender_id,
            gs_receiver_id=original.gs_receiver_id,
            trading_partner_id=original.trading_partner_id,
            edi_data=modified_payload,
        )

        if original.direction == Direction.INBOUND:
            # Re-transform the inbound file
            transform_event = TransformRequestedEvent(
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                trading_partner_id=new_msg.trading_partner_id,
                sender_id=new_msg.sender_id,
                receiver_id=new_msg.receiver_id,
                direction=str(new_msg.direction.value) if new_msg.direction else None,
                edi_message_id=new_msg.id,
            )
            new_msg.add_domain_event(transform_event)
            event_type = TraceEventType.MODIFY_AND_REPLAY_TRANSFORM.value
        else:
            # Re-deliver the outbound file
            deliver_event = DeliverRequestedEvent(
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                trading_partner_id=new_msg.trading_partner_id,
                transaction_type=new_msg.transaction_type,
                direction=str(new_msg.direction.value) if new_msg.direction else None,
            )
            new_msg.add_domain_event(deliver_event)
            event_type = TraceEventType.MODIFY_AND_REPLAY_DELIVER.value

        await self.uow.transactions.save(new_msg)

        # Audit event on the OLD trace
        old_audit = TraceEventDomainModel(
            id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
            tenant_id=tenant_id,
            trace_id=original_trace_id,
            event_type=event_type,
            actor=actor,
            metadata={"new_trace_id": new_trace_id},
        )
        await self.uow.transactions.save_trace_event(old_audit)

        # Audit event on the NEW trace
        new_audit = TraceEventDomainModel(
            id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
            tenant_id=tenant_id,
            trace_id=new_trace_id,
            event_type=TraceEventType.CREATED_FROM_MODIFICATION.value,
            actor=actor,
            metadata={"parent_trace_id": original_trace_id, "original_trace_id": root_trace_id},
        )
        await self.uow.transactions.save_trace_event(new_audit)

        await self.uow.commit()
        return new_trace_id

    async def _handle_edi_json(
        self,
        tenant_id: str,
        original_trace_id: str,
        new_trace_id: str,
        modified_payload: str,
        actor: str,
        original: EdiJsonDomainModel,
    ) -> str:
        try:
            parsed_payload = json.loads(modified_payload)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON payload provided for correction: {e}") from e

        root_trace_id = original.original_trace_id or original.trace_id

        new_json = EdiJsonDomainModel(
            id=generate_id(DomainIdPrefix.EDI_JSON.value),
            tenant_id=tenant_id,
            trace_id=new_trace_id,
            parent_trace_id=original.trace_id,
            original_trace_id=root_trace_id,
            direction=original.direction,
            status=RecordStatus.RECEIVED
            if original.direction == Direction.OUTBOUND
            else RecordStatus.TRANSFORMED,
            trading_partner_id=original.trading_partner_id,
            transaction_type=original.transaction_type,
            standard=original.standard,
            business_metadata=original.business_metadata,
            payload=parsed_payload,
        )

        if original.direction == Direction.OUTBOUND:
            transform_event = TransformRequestedEvent(
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                trading_partner_id=new_json.trading_partner_id,
                direction=str(new_json.direction.value) if new_json.direction else None,
            )
            new_json.add_domain_event(transform_event)
            event_type = TraceEventType.MODIFY_AND_REPLAY_TRANSFORM.value
        else:
            deliver_event = DeliverRequestedEvent(
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                trading_partner_id=new_json.trading_partner_id,
                transaction_type=new_json.transaction_type,
                direction=str(new_json.direction.value) if new_json.direction else None,
            )
            new_json.add_domain_event(deliver_event)
            event_type = TraceEventType.MODIFY_AND_REPLAY_DELIVER.value

        await self.uow.transactions.save_json(new_json)

        old_audit = TraceEventDomainModel(
            id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
            tenant_id=tenant_id,
            trace_id=original_trace_id,
            event_type=event_type,
            actor=actor,
            metadata={"new_trace_id": new_trace_id},
        )
        await self.uow.transactions.save_trace_event(old_audit)

        new_audit = TraceEventDomainModel(
            id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
            tenant_id=tenant_id,
            trace_id=new_trace_id,
            event_type=TraceEventType.CREATED_FROM_MODIFICATION.value,
            actor=actor,
            metadata={"parent_trace_id": original_trace_id, "original_trace_id": root_trace_id},
        )
        await self.uow.transactions.save_trace_event(new_audit)

        await self.uow.commit()
        return new_trace_id
