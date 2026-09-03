import contextlib
import copy
from collections.abc import Callable
from typing import cast

import structlog
from seedwork.domain.types import JsonValue

from edi.core.pipeline.metadata_extractor import MetadataExtractorService
from edi.core.pipeline.models import EdiWebhookPayload
from edi.domain.direction import MessageDirection
from edi.domain.events import PipelineEventType, TransformCompleted
from edi.domain.status import MessageStatus
from edi.ports.outbound.transformer_port import TransformerPort
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class ComputeTransformUseCase:
    """
    Application Use Case running exclusively in the Compute Worker.
    Executes heavy EDI to JSON transformations and performs metadata extraction.
    """

    def __init__(
        self,
        uow_factory: Callable[[], contextlib.AbstractAsyncContextManager[DataPlaneUnitOfWorkPort]],
        transformer: TransformerPort,
    ) -> None:
        self.uow_factory = uow_factory
        self.transformer = transformer

    async def execute(self, trace_id: str, standard: str, transaction_type: str) -> None:
        """Transforms an inbound X12 EDI payload to JSON and dispatches TRANSFORM_COMPLETED."""
        logger.info(
            "compute_transform.started",
            trace_id=trace_id,
            standard=standard,
            transaction_type=transaction_type,
        )

        async with self.uow_factory() as uow, uow:
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
                payload=raw_payload, standard=standard, transaction_type=transaction_type
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
                await uow.transactions.get_route(
                    MessageDirection.INBOUND,
                    str(edi_msg.sender_id),
                    str(edi_msg.receiver_id),
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

                await uow.transactions.save_edi_json(
                    trace_id=trace_id,
                    direction=MessageDirection.INBOUND.value,
                    partnership_id=partnership_id_str,
                    transaction_type=txn_type,
                    standard=standard,
                    sender_id=edi_msg.sender_id,
                    receiver_id=edi_msg.receiver_id,
                    gs_sender_id=gs_sender,
                    gs_receiver_id=gs_receiver,
                    business_metadata=cast("dict[str, JsonValue]", business_metadata),
                    payload=cast("dict[str, JsonValue]", json_dict),
                    status=MessageStatus.PARSED.value,
                    tenant_id=edi_msg.tenant_id,
                )
                logger.info(
                    "compute_transform.edi_json_saved",
                    trace_id=trace_id,
                    transaction_type=txn_type,
                )
                json_payloads.append(json_dict)

            # Metadata to emit in event
            txn_type_for_parent = transformed_txns[0].transaction_type if transformed_txns else None

            # 3. Build the complete EDI Webhook envelope
            trading_partner_id = partnership_id_str

            webhook_url = None
            if route and route.webhook_id:
                partner = await uow.transactions.get_webhook(str(route.webhook_id))
                if partner:
                    webhook_url = partner.url
                    logger.info(
                        "compute_transform.webhook_resolved",
                        trace_id=trace_id,
                        webhook_id=route.webhook_id,
                        webhook_url=webhook_url,
                    )
                else:
                    logger.warning(
                        "compute_transform.webhook_not_found",
                        trace_id=trace_id,
                        webhook_id=route.webhook_id,
                    )

            envelope = EdiWebhookPayload.build(
                trace_id=trace_id,
                direction=MessageDirection.INBOUND.value,
                sender_id=edi_msg.sender_id,
                receiver_id=edi_msg.receiver_id,
                trading_partner_id=trading_partner_id,
                format_standard=standard,
                transactions=json_payloads,
            )

            # Save ApiGateway to DB as a single webhook delivery
            await uow.transactions.save_api_payload(
                trace_id=trace_id,
                tenant_id=edi_msg.tenant_id,
                direction=MessageDirection.OUTBOUND.value,
                payload=envelope.model_dump(),
                status=MessageStatus.PENDING_DELIVERY.value,
                transaction_type=standard,
                webhook_url=webhook_url,
            )
            logger.info("compute_transform.api_payload_saved", trace_id=trace_id)

            # 4. Record TRANSFORM_COMPLETED on the aggregate — repository drains to outbox.
            edi_msg.add_domain_event(
                TransformCompleted(
                    trace_id=trace_id,
                    tenant_id=edi_msg.tenant_id or "",
                    direction=MessageDirection.INBOUND.value,
                    gs_sender_id=gs_sender_global,
                    gs_receiver_id=gs_receiver_global,
                    transaction_type=txn_type_for_parent,
                )
            )
            await uow.transactions.save(edi_msg)
            logger.info(
                "compute_transform.outbox_event_dispatched",
                trace_id=trace_id,
                event_type=PipelineEventType.TRANSFORM_COMPLETED.value,
            )

            await uow.commit()

        logger.info("compute_transform.completed", trace_id=trace_id)
