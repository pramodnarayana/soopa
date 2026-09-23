import contextlib
import copy
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import structlog
from seedwork.domain.types import JsonDict

from edi.core.pipeline.metadata_extractor import MetadataExtractorService
from edi.domain.enums import EdiDirection, MessageStatus, PipelineEventType
from edi.domain.events import TransformFailed, TransformSuccessful
from edi.ports.outbound.transaction_repository import CreateEdiJsonCommand
from edi.ports.outbound.transformer_port import TransformerPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)

from edi.domain.enums import EdiStandard


@dataclass(frozen=True, kw_only=True)
class ComputeTransformCommand:
    trace_id: str
    tenant_id: str
    idempotency_key: str
    standard: str = EdiStandard.X12.name
    transaction_type: str | None = None

    def __post_init__(self) -> None:
        if not self.trace_id or not self.trace_id.strip():
            raise ValueError("Required field 'trace_id' is missing or empty")
        if not self.tenant_id or not self.tenant_id.strip():
            raise ValueError("Required field 'tenant_id' is missing or empty")
        if not self.idempotency_key or not self.idempotency_key.strip():
            raise ValueError("Required field 'idempotency_key' is missing or empty")


class ComputeTransformUseCase:
    """
    Application Use Case running exclusively in the Compute Worker.
    Executes heavy EDI to JSON transformations and performs metadata extraction.
    """

    def __init__(
        self,
        transformer: TransformerPort,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
    ) -> None:
        self.transformer = transformer
        self.uow_factory = uow_factory

    async def execute(self, command: ComputeTransformCommand) -> None:
        """Transforms an inbound X12 EDI payload to JSON and dispatches TRANSFORMATION_COMPLETED."""
        trace_id = command.trace_id.strip()
        standard = command.standard
        transaction_type = command.transaction_type

        logger.info(
            "compute_transform.started",
            trace_id=trace_id,
            standard=standard,
            transaction_type=transaction_type,
        )

        try:
            async with self.uow_factory() as uow, uow:
                # 0. Idempotency Check — use per-event idempotency_key, NOT trace_id.
                # trace_id is stable across replays; using it would cause replays to be
                # silently dropped as duplicates.
                is_new = await uow.record_idempotency(command.tenant_id, command.idempotency_key)
                if not is_new:
                    logger.info("compute_transform.duplicate_skipped", trace_id=trace_id)
                    return

                edi_msg = await uow.transactions.get_edi_message(trace_id)
                if not edi_msg:
                    logger.warning("compute_transform.edi_message_not_found", trace_id=trace_id)
                    raise ValueError(f"No EDI message found for trace_id={trace_id}")

                if not edi_msg.edi_data:
                    logger.warning("compute_transform.edi_data_missing", trace_id=trace_id)
                    raise ValueError(f"No EDI data found for trace_id={trace_id}")

                raw_payload = edi_msg.edi_data.encode("utf-8")

                # 1. Transform
                transformed_txns = await self.transformer.transform_edi_to_json(
                    payload=raw_payload, standard=standard, transaction_type=transaction_type or ""
                )
                if not transformed_txns:
                    logger.warning(
                        "compute_transform.transform_failed",
                        trace_id=trace_id,
                        transaction_type=transaction_type,
                    )
                    raise ValueError(f"Failed to transform EDI transaction {transaction_type}")

                logger.info(
                    "compute_transform.transform_succeeded",
                    trace_id=trace_id,
                    transaction_count=len(transformed_txns),
                )

                # 2. Process each transaction
                extractor = MetadataExtractorService()

                json_payloads = []
                gs_sender_global = None
                gs_receiver_global = None

                transaction_type_global = (
                    transformed_txns[0].transaction_type
                    if transformed_txns
                    else edi_msg.transaction_type
                )
                route = (
                    await uow.inbound_routes.get_inbound_route(
                        str(edi_msg.sender_id),
                        str(edi_msg.receiver_id),
                        str(edi_msg.tenant_id),
                        str(transaction_type_global) if transaction_type_global else "",
                    )
                    if edi_msg.sender_id and edi_msg.receiver_id
                    else None
                )
                partnership_id_str = route.trading_partner_id if route else None
                logger.info(
                    "compute_transform.route_resolved",
                    trace_id=trace_id,
                    partner_id=partnership_id_str,
                    has_route=route is not None,
                )

                for txn in transformed_txns:
                    txn_type = txn.transaction_type
                    gs_sender = txn.gs_sender_id
                    gs_receiver = txn.gs_receiver_id

                    if not gs_sender_global and gs_sender:
                        gs_sender_global = gs_sender
                        gs_receiver_global = gs_receiver

                    json_dict = copy.deepcopy(txn.payload) if txn.payload else {}
                    if isinstance(json_dict, dict):
                        json_dict["transaction_type"] = txn_type
                    business_metadata = extractor.extract(txn_type, json_dict)

                    await uow.transactions.create_edi_json(
                        command=CreateEdiJsonCommand(
                            trace_id=trace_id,
                            tenant_id=edi_msg.tenant_id,
                            direction=EdiDirection.INBOUND,
                            trading_partner_id=partnership_id_str,
                            transaction_type=txn_type,
                            standard=standard,
                            business_metadata=cast(JsonDict, business_metadata),
                            payload=cast(JsonDict, json_dict),
                            status=MessageStatus.PARSED,
                            replay_count=edi_msg.replay_count,
                            parent_trace_id=edi_msg.parent_trace_id,
                            original_trace_id=edi_msg.original_trace_id,
                        )
                    )
                    logger.info(
                        "compute_transform.edi_json_saved",
                        trace_id=trace_id,
                        transaction_type=txn_type,
                    )
                    json_payloads.append(json_dict)

                # Metadata to emit in event
                txn_type_for_parent = (
                    transformed_txns[0].transaction_type if transformed_txns else None
                )

                # Payload construction and API Gateway logging are now completely decoupled
                # and delegated strictly to the WebhookDeliveryWorker.
                # 4. Record TRANSFORMATION_SUCCESSFUL on the aggregate — repository drains to outbox.
                edi_msg.add_domain_event(
                    TransformSuccessful(
                        trace_id=trace_id,
                        tenant_id=edi_msg.tenant_id or "",
                        direction=EdiDirection.INBOUND.value,
                        isa_sender_id=edi_msg.sender_id,
                        isa_receiver_id=edi_msg.receiver_id,
                        gs_sender_id=gs_sender_global,
                        gs_receiver_id=gs_receiver_global,
                        transaction_type=txn_type_for_parent,
                    )
                )
                await uow.transactions.save(edi_msg)
                logger.info(
                    "compute_transform.outbox_event_dispatched",
                    trace_id=trace_id,
                    event_type=PipelineEventType.TRANSFORMATION_SUCCESSFUL.value,
                )

                await uow.commit()

            logger.info("compute_transform.completed", trace_id=trace_id)
        except Exception as e:
            logger.exception("compute_transform.failed", trace_id=trace_id, error=str(e))

            # Emit failure domain event in a separate transaction
            async with self.uow_factory() as failure_uow, failure_uow:
                edi_msg_fallback = await failure_uow.transactions.get_edi_message(trace_id)
                if edi_msg_fallback:
                    edi_msg_fallback.add_domain_event(
                        TransformFailed(
                            trace_id=trace_id,
                            tenant_id=edi_msg_fallback.tenant_id or command.tenant_id,
                            direction=EdiDirection.INBOUND.value,
                            failure_reason=str(e),
                        )
                    )
                    await failure_uow.transactions.save(edi_msg_fallback)
                    await failure_uow.commit()

            raise
