import structlog
from seedwork import generate_id
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix

from edi.domain.enums import EdiDirection, MessageStatus, TraceEventType
from edi.domain.events import DeliverRequestedEvent, TransformRequestedEvent
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.base import RecordStatus
from edi.domain.models.transactions import (
    EdiJsonDomainModel,
    EdiMessageDomainModel,
    TraceEventDomainModel,
)
from edi.ports.outbound.transaction_repository import CreateApiGatewayCommand, CreateEdiJsonCommand
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

        root_trace_id = original.original_trace_id or trace_id
        new_trace_id = generate_id(SystemIdPrefix.TRACE)

        logger.info(
            "replay_transform.started",
            tenant_id=tenant_id,
            original_trace_id=trace_id,
            root_trace_id=root_trace_id,
            new_trace_id=new_trace_id,
            actor=actor,
        )

        if original.direction == EdiDirection.INBOUND:
            new_edi_message = EdiMessageDomainModel(
                id=generate_id(DomainIdPrefix.EDI_MESSAGE),
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                direction=original.direction,
                status=MessageStatus.RECEIVED,
                parent_trace_id=trace_id,
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
            )
            new_edi_message.add_domain_event(transform_event)
            await self.uow.transactions.save(new_edi_message)

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

            edi_json_aggregate = EdiJsonDomainModel(
                id=generate_id(SystemIdPrefix.GENERIC),
                tenant_id=tenant_id,
                trace_id=new_trace_id,
                direction=original.direction,
                transaction_type=original_json.transaction_type,
                trading_partner_id=original_json.trading_partner_id,
                business_metadata=original_json.business_metadata,
                payload=original_json.payload,
                status=RecordStatus.RECEIVED,
                parent_trace_id=trace_id,
                original_trace_id=root_trace_id,
                is_replay=True,
            )

            transform_event = TransformRequestedEvent(
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                trading_partner_id=original.trading_partner_id,
                direction=str(original.direction.value) if original.direction else None,
            )
            edi_json_aggregate.add_domain_event(transform_event)
            await self.uow.transactions.save_json(edi_json_aggregate)

        audit_event = TraceEventDomainModel(
            id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
            tenant_id=tenant_id,
            trace_id=trace_id,
            event_type=TraceEventType.REPLAY_TRANSFORM.value,
            actor=actor,
            metadata={"replay_trace_id": new_trace_id},
        )
        await self.uow.transactions.save_trace_event(audit_event)

        logger.info(
            "replay_transform.pre_commit",
            tenant_id=tenant_id,
            new_trace_id=new_trace_id,
            direction=str(original.direction.value) if original.direction else None,
        )
        await self.uow.commit()
        logger.info(
            "replay_transform.post_commit",
            tenant_id=tenant_id,
            new_trace_id=new_trace_id,
        )

        logger.info(
            "replay_transform.completed",
            tenant_id=tenant_id,
            original_trace_id=trace_id,
            new_trace_id=new_trace_id,
        )
        return new_trace_id

    async def retry_deliver(self, tenant_id: str, trace_id: str, actor: str) -> str:
        """
        Immutable Replay — DELIVERY checkpoint.

        Creates a brand-new EdiMessage aggregate in TRANSFORMED state with a fresh
        trace_id, emitting a DeliverRequestedEvent that skips the transform stage.
        The original record is NEVER mutated.
        Returns the new trace_id so the caller can navigate directly to the replay.
        """
        original = await self.uow.transactions.get_edi_message(trace_id)
        if not original:
            raise TransactionNotFoundError(trace_id=trace_id)

        root_trace_id = original.original_trace_id or trace_id
        new_trace_id = generate_id(SystemIdPrefix.TRACE)

        logger.info(
            "replay_deliver.started",
            tenant_id=tenant_id,
            original_trace_id=trace_id,
            root_trace_id=root_trace_id,
            new_trace_id=new_trace_id,
            actor=actor,
        )

        new_edi_message = EdiMessageDomainModel(
            id=generate_id(DomainIdPrefix.EDI_MESSAGE),
            trace_id=new_trace_id,
            tenant_id=tenant_id,
            direction=original.direction,
            status=MessageStatus.TRANSFORMED,
            parent_trace_id=trace_id,
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
        )
        new_edi_message.add_domain_event(deliver_event)

        await self.uow.transactions.save(new_edi_message)

        original_json = await self.uow.transactions.get_edi_json(trace_id)
        if original_json:
            await self.uow.transactions.create_edi_json(
                CreateEdiJsonCommand(
                    trace_id=new_trace_id,
                    tenant_id=tenant_id,
                    direction=original.direction,
                    status=original_json.status,
                    trading_partner_id=original_json.trading_partner_id,
                    transaction_type=original_json.transaction_type,
                    payload=original_json.payload,
                    parent_trace_id=trace_id,
                    original_trace_id=root_trace_id,
                    is_replay=True,
                    business_metadata=original_json.business_metadata,
                )
            )

        if original.direction == EdiDirection.INBOUND:
            api_payload = await self.uow.transactions.get_api_payload(trace_id)
            if api_payload:
                await self.uow.transactions.create_api_gateway(
                    CreateApiGatewayCommand(
                        trace_id=new_trace_id,
                        tenant_id=tenant_id,
                        direction=original.direction,
                        status=MessageStatus.PENDING_DELIVERY,
                        transaction_type=original.transaction_type,
                        payload=api_payload.get("payload"),
                        parent_trace_id=trace_id,
                        original_trace_id=root_trace_id,
                    )
                )

        audit_event = TraceEventDomainModel(
            id=generate_id(DomainIdPrefix.EDI_TRACE_EVENT),
            tenant_id=tenant_id,
            trace_id=trace_id,
            event_type=TraceEventType.REPLAY_DELIVER.value,
            actor=actor,
            metadata={"replay_trace_id": new_trace_id},
        )
        await self.uow.transactions.save_trace_event(audit_event)

        await self.uow.commit()

        logger.info(
            "replay_deliver.completed",
            tenant_id=tenant_id,
            original_trace_id=trace_id,
            new_trace_id=new_trace_id,
        )
        return new_trace_id
