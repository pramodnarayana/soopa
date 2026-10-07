import contextlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, cast

import structlog
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.events import EventEnvelope
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix
from seedwork.utils import generate_deterministic_id, generate_id

from edi.domain.enums import (
    EdiDirection,
    EdiStandard,
    PipelineEventType,
)
from edi.domain.exceptions import TransactionNotFoundError
from edi.domain.models.headers import EdiEnvelopeHeaders
from edi.domain.models.transactions import EdiMessageDomainModel
from edi.domain.types import AstNode
from edi.ports.outbound.transformer_port import TransformerPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ComputeOutboundTransformCommand:
    trace_id: str
    tenant_id: str
    idempotency_key: str
    edi_headers: EdiEnvelopeHeaders
    standard: str = EdiStandard.X12.value

    def __post_init__(self) -> None:
        if not self.trace_id or not self.trace_id.strip():
            raise ValueError("Required field 'trace_id' is missing or empty")
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("Required field 'tenant_id' is missing or empty")
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValueError("Required field 'idempotency_key' is missing or empty")


class ComputeOutboundTransformUseCase:
    """
    Application Use Case running exclusively in the Compute Worker.
    Executes heavy JSON to EDI transformations.
    """

    def __init__(
        self,
        transformer: TransformerPort,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        publisher: OutboxPublisherPort,
    ) -> None:
        self.transformer = transformer
        self.uow_factory = uow_factory
        self.publisher = publisher

    async def _save_edi_message(
        self,
        uow: DataPlaneUnitOfWorkPort,
        edi_json: Any,
        trace_id: str,
        edi_str: str,
        standard: str,
        edi_headers: EdiEnvelopeHeaders,
        trading_partner_id: str | None,
    ) -> Sequence[EventEnvelope]:

        if not trading_partner_id:
            business_metadata = edi_json.business_metadata or {}
            routing_meta = business_metadata.get("_routing")
            if isinstance(routing_meta, dict):
                tp_id = routing_meta.get("trading_partner_id")
                trading_partner_id = str(tp_id) if tp_id else None

        existing_msg = await uow.transactions.get_edi_message(trace_id)
        if existing_msg:
            edi_msg = existing_msg
            edi_msg.mark_outbound_pending_delivery(
                edi_data=edi_str,
                format_standard=standard,
                transaction_type=edi_headers.transaction_type,
                sender_id=edi_headers.isa_sender_id,
                receiver_id=edi_headers.isa_receiver_id,
                gs_sender_id=edi_headers.gs_sender_id,
                gs_receiver_id=edi_headers.gs_receiver_id,
                trading_partner_id=trading_partner_id,
            )
        else:
            edi_msg = EdiMessageDomainModel.create_outbound(
                id=generate_id(DomainIdPrefix.EDI_MESSAGE.value),
                trace_id=trace_id,
                tenant_id=edi_json.tenant_id or "",
                replay_count=edi_json.replay_count,
                parent_trace_id=edi_json.parent_trace_id,
                original_trace_id=edi_json.original_trace_id,
                edi_data=edi_str,
                format_standard=standard,
                transaction_type=edi_headers.transaction_type,
                sender_id=edi_headers.isa_sender_id,
                receiver_id=edi_headers.isa_receiver_id,
                gs_sender_id=edi_headers.gs_sender_id,
                gs_receiver_id=edi_headers.gs_receiver_id,
                trading_partner_id=trading_partner_id,
            )
        return await uow.transactions.save(edi_msg)

    async def execute(self, command: ComputeOutboundTransformCommand) -> None:
        """Transforms an outbound JSON payload to X12 EDI."""
        trace_id = command.trace_id.strip()
        standard = command.standard

        logger.info(
            "compute_outbound_transform.started",
            trace_id=trace_id,
            standard=standard,
            transaction_type=command.edi_headers.transaction_type,
        )

        try:
            async with self.uow_factory() as uow, uow:
                # 0. Idempotency Check — use per-event idempotency_key, NOT trace_id.
                # trace_id is stable across replays; using it would cause replays to be
                # silently dropped as duplicates.
                is_new = await uow.record_idempotency(command.tenant_id, command.idempotency_key)
                if not is_new:
                    logger.info("compute_outbound_transform.duplicate_skipped", trace_id=trace_id)
                    return

                edi_json = await uow.transactions.get_edi_json(trace_id)
                if not edi_json:
                    logger.warning(
                        "compute_outbound_transform.edi_json_not_found", trace_id=trace_id
                    )
                    raise TransactionNotFoundError(trace_id)

                json_payload = edi_json.payload
                if not json_payload or not (
                    isinstance(json_payload, dict)
                    or (
                        isinstance(json_payload, list)
                        and all(isinstance(node, dict) for node in json_payload)
                    )
                ):
                    raise TransactionNotFoundError(trace_id)

                logger.info(
                    "compute_outbound_transform.resolved",
                    trace_id=trace_id,
                    transaction_type=command.edi_headers.transaction_type,
                    standard=standard,
                )

                # 1. Transform
                raw_edi_bytes = await self.transformer.transform_json_to_edi(
                    payload=cast(AstNode | list[AstNode], json_payload),
                    standard=standard,
                    transaction_type=command.edi_headers.transaction_type,
                    edi_headers=command.edi_headers,
                )

                edi_str = raw_edi_bytes.decode("utf-8")
                trading_partner_id = edi_json.trading_partner_id

                # 2. Save EdiMessage
                envelopes = await self._save_edi_message(
                    uow=uow,
                    edi_json=edi_json,
                    trace_id=trace_id,
                    edi_str=edi_str,
                    standard=standard,
                    edi_headers=command.edi_headers,
                    trading_partner_id=trading_partner_id,
                )

                logger.info("compute_outbound_transform.edi_message_saved", trace_id=trace_id)

                # 3. Dispatch TRANSFORMATION_SUCCESSFUL
                # Seed from command.idempotency_key (not trace_id) so replays produce a
                # distinct outbox key and are not silently dropped as duplicates.
                transform_successful_key = generate_deterministic_id(
                    SystemIdPrefix.IDEMPOTENCY, command.idempotency_key, "TRANSFORMATION_SUCCESSFUL"
                )
                envelope = await uow.outbox.append_event(
                    tenant_id=edi_json.tenant_id,
                    idempotency_key=transform_successful_key,
                    event_type=PipelineEventType.TRANSFORMATION_SUCCESSFUL.value,
                    payload={
                        "trace_id": trace_id,
                        "tenant_id": edi_json.tenant_id,
                        "direction": EdiDirection.OUTBOUND.value,
                        "trading_partner_id": trading_partner_id,
                        "standard": standard,
                        "isa_sender_id": command.edi_headers.isa_sender_id,
                        "isa_receiver_id": command.edi_headers.isa_receiver_id,
                        "gs_sender_id": command.edi_headers.gs_sender_id,
                        "gs_receiver_id": command.edi_headers.gs_receiver_id,
                    },
                )

                await uow.commit()

                for env in envelopes:
                    await self.publisher.publish(env)
                await self.publisher.publish(envelope)

            logger.info("compute_outbound_transform.completed", trace_id=trace_id)
        except Exception as e:
            logger.exception("compute_outbound_transform.failed", trace_id=trace_id, error=str(e))
            async with self.uow_factory() as failure_uow, failure_uow:
                edi_json_fallback = await failure_uow.transactions.get_edi_json(trace_id)
                if edi_json_fallback:
                    event_key = generate_deterministic_id(
                        SystemIdPrefix.IDEMPOTENCY, command.idempotency_key, "TRANSFORMATION_FAILED"
                    )
                    failure_envelope = await failure_uow.outbox.append_event(
                        tenant_id=edi_json_fallback.tenant_id,
                        idempotency_key=event_key,
                        event_type=PipelineEventType.TRANSFORMATION_FAILED.value,
                        payload={
                            "trace_id": trace_id,
                            "direction": EdiDirection.OUTBOUND.value,
                            "tenant_id": edi_json_fallback.tenant_id,
                            "failure_reason": str(e),
                        },
                    )
                    await failure_uow.commit()
                    await self.publisher.publish(failure_envelope)
