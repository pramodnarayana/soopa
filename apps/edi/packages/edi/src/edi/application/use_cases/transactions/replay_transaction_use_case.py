import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork import generate_id
from seedwork.events import EventEnvelope
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix

from edi.domain.enums import EdiDirection
from edi.domain.events import DeliverRequestedEvent, TransformRequestedEvent
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.transactions import EdiJsonDomainModel, EdiMessageDomainModel
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class ReplayTransactionUseCase:
    def __init__(self, uow: DataPlaneUnitOfWorkPort, publisher: OutboxPublisherPort) -> None:
        self.uow = uow
        self.publisher = publisher

    async def retry_transform(self, tenant_id: str, trace_id: str, actor: str) -> str:
        """
        Immutable Replay — TRANSFORM checkpoint.
        Inbound: clones EdiMessage only (Stage 1).
        Outbound: clones EdiJson only (Stage 1).
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
            source_msg = original_msg
            if not source_msg and original_json and original_json.parent_trace_id:
                source_msg = await self.uow.transactions.get_edi_message(
                    original_json.parent_trace_id
                )
            if not source_msg:
                raise TransactionNotFoundError(trace_id=trace_id)
            new_trace_id = generate_id(SystemIdPrefix.TRACE.value)
            new_id = generate_id(DomainIdPrefix.EDI_MESSAGE.value)
            cloned_msg = source_msg.clone_for_transform_retry(new_id, new_trace_id)
            transform_event = TransformRequestedEvent(
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                trading_partner_id=cloned_msg.trading_partner_id,
                sender_id=cloned_msg.sender_id,
                receiver_id=cloned_msg.receiver_id,
                direction=str(cloned_msg.direction.value) if cloned_msg.direction else None,
                edi_message_id=cloned_msg.id,
            )
            cloned_msg.mark_replay_triggered(actor)
            cloned_msg.add_domain_event(transform_event)
            envelopes = await self.uow.transactions.save(cloned_msg)

        elif direction == EdiDirection.OUTBOUND:
            source_json = original_json
            if not source_json and original_msg and original_msg.parent_trace_id:
                source_json = await self.uow.transactions.get_edi_json(original_msg.parent_trace_id)
            if not source_json:
                raise TransactionNotFoundError(trace_id=trace_id)
            new_trace_id = generate_id(SystemIdPrefix.TRACE.value)
            new_id = generate_id(DomainIdPrefix.EDI_JSON.value)
            cloned_json = source_json.clone_for_transform_retry(new_id, new_trace_id)
            transform_event = TransformRequestedEvent(
                trace_id=new_trace_id,
                tenant_id=tenant_id,
                trading_partner_id=cloned_json.trading_partner_id,
                direction=str(cloned_json.direction.value) if cloned_json.direction else None,
            )
            cloned_json.mark_replay_triggered(actor)
            cloned_json.add_domain_event(transform_event)
            envelopes = await self.uow.transactions.save_json(cloned_json)
        else:
            raise TransactionNotFoundError(trace_id=trace_id)

        logger.info(
            "replay_transform.pre_commit",
            tenant_id=tenant_id,
            trace_id=new_trace_id,
            direction=str(direction.value) if direction else None,
        )
        await self.uow.commit()
        for env in envelopes:
            await self.publisher.publish(env)
            await self.uow.outbox.mark_completed(env.id)
        logger.info(
            "replay_transform.completed",
            tenant_id=tenant_id,
            trace_id=new_trace_id,
        )
        return new_trace_id

    async def retry_deliver(self, tenant_id: str, trace_id: str, actor: str) -> str:
        """
        Immutable Replay — DELIVERY checkpoint.
        Inbound: clones EdiJson only (Stage 2). Preceding EdiMessage is NOT cloned.
        Outbound: clones EdiMessage only (Stage 2). Preceding EdiJson is NOT cloned.
        """
        original_msg = await self.uow.transactions.get_edi_message(trace_id)
        original_json = await self.uow.transactions.get_edi_json(trace_id)

        logger.info(
            "replay_deliver.lookup",
            tenant_id=tenant_id,
            trace_id=trace_id,
            found_msg=original_msg is not None,
            found_json=original_json is not None,
        )

        if not original_msg and not original_json:
            raise TransactionNotFoundError(trace_id=trace_id)

        direction = (
            original_msg.direction
            if original_msg
            else (original_json.direction if original_json else None)
        )

        logger.info(
            "replay_deliver.started",
            tenant_id=tenant_id,
            trace_id=trace_id,
            actor=actor,
            direction=str(direction.value) if direction else None,
        )

        if direction == EdiDirection.INBOUND:
            new_trace_id, envelopes = await self._retry_deliver_inbound(
                tenant_id, trace_id, actor, original_msg
            )
        elif direction == EdiDirection.OUTBOUND:
            new_trace_id, envelopes = await self._retry_deliver_outbound(
                tenant_id, trace_id, actor, original_msg, original_json
            )
        else:
            raise TransactionNotFoundError(trace_id=trace_id)

        await self.uow.commit()
        for env in envelopes:
            await self.publisher.publish(env)
            await self.uow.outbox.mark_completed(env.id)

        logger.info(
            "replay_deliver.completed",
            tenant_id=tenant_id,
            trace_id=new_trace_id,
            direction=str(direction.value) if direction else None,
        )
        return new_trace_id

    async def _retry_deliver_inbound(
        self,
        tenant_id: str,
        trace_id: str,
        actor: str,
        original_msg: EdiMessageDomainModel | None,
    ) -> tuple[str, list[EventEnvelope]]:
        source_jsons = await self.uow.transactions.get_edi_jsons_by_trace_id(trace_id, tenant_id)
        if not source_jsons and original_msg and original_msg.parent_trace_id:
            source_jsons = await self.uow.transactions.get_edi_jsons_by_trace_id(
                original_msg.parent_trace_id, tenant_id
            )
        if not source_jsons:
            raise TransactionNotFoundError(trace_id=trace_id)
        new_trace_id = generate_id(SystemIdPrefix.TRACE.value)
        envelopes: list[EventEnvelope] = []
        for i, source_json in enumerate(source_jsons):
            new_id = generate_id(DomainIdPrefix.EDI_JSON.value)
            cloned_json = source_json.clone_for_delivery_retry(new_id, new_trace_id)
            cloned_json.mark_replay_triggered(actor)
            if i == 0:
                deliver_event = DeliverRequestedEvent(
                    trace_id=new_trace_id,
                    tenant_id=tenant_id,
                    trading_partner_id=cloned_json.trading_partner_id,
                    transaction_type=cloned_json.transaction_type,
                    direction=str(cloned_json.direction.value) if cloned_json.direction else None,
                )
                cloned_json.add_domain_event(deliver_event)
            saved_envs = await self.uow.transactions.save_json(cloned_json)
            envelopes.extend(saved_envs)
        return new_trace_id, envelopes

    async def _retry_deliver_outbound(
        self,
        tenant_id: str,
        trace_id: str,
        actor: str,
        original_msg: EdiMessageDomainModel | None,
        original_json: EdiJsonDomainModel | None,
    ) -> tuple[str, list[EventEnvelope]]:
        source_msg = original_msg
        if not source_msg and original_json and original_json.parent_trace_id:
            source_msg = await self.uow.transactions.get_edi_message(original_json.parent_trace_id)
        if not source_msg:
            raise TransactionNotFoundError(trace_id=trace_id)
        new_trace_id = generate_id(SystemIdPrefix.TRACE.value)
        new_id = generate_id(DomainIdPrefix.EDI_MESSAGE.value)
        cloned_msg = source_msg.clone_for_delivery_retry(new_id, new_trace_id)
        deliver_event = DeliverRequestedEvent(
            trace_id=new_trace_id,
            tenant_id=tenant_id,
            trading_partner_id=cloned_msg.trading_partner_id,
            transaction_type=cloned_msg.transaction_type,
            direction=str(cloned_msg.direction.value) if cloned_msg.direction else None,
        )
        cloned_msg.mark_replay_triggered(actor)
        cloned_msg.add_domain_event(deliver_event)
        envelopes = list(await self.uow.transactions.save(cloned_msg))
        return new_trace_id, envelopes
