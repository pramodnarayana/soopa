import uuid

import structlog
from edi.ports.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort
from edi.ports.transformer_port import TransformerPort

from edi.core.pipeline.metadata_extractor import MetadataExtractorService
from edi.core.pipeline.models import EdiWebhookPayload
from edi.domain.direction import MessageDirection
from edi.domain.events import PipelineEventType
from edi.domain.status import MessageStatus

logger = structlog.get_logger(__name__)


class ComputeTransformUseCase:
    """
    Application Use Case running exclusively in the Compute Worker.
    Executes heavy EDI to JSON transformations and performs metadata extraction.
    """

    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        transformer: TransformerPort,
    ) -> None:
        self.uow = uow
        self.transformer = transformer

    async def execute(self, trace_id: str, standard: str, transaction_type: str) -> None:
        """Transforms an inbound X12 EDI payload to JSON and dispatches TRANSFORM_COMPLETED."""
        logger.info("compute_transform.started", trace_id=trace_id)

        async with self.uow:
            edi_msg = await self.uow.repository.get_edi_message(trace_id)
            if not edi_msg:
                raise ValueError(f"No EDI message found for trace_id={trace_id}")

            if not edi_msg.edi_data:
                raise ValueError(f"No EDI data found for trace_id={trace_id}")

            raw_payload = edi_msg.edi_data.encode("utf-8")

            # 1. Transform
            transformed_txns = await self.transformer.transform_edi_to_json(
                payload=raw_payload, standard=standard, transaction_type=transaction_type
            )
            if not transformed_txns:
                raise ValueError(f"Failed to transform EDI transaction {transaction_type}")

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
                await self.uow.repository.get_route(
                    MessageDirection.INBOUND.value,
                    str(edi_msg.sender_id),
                    str(edi_msg.receiver_id),
                    str(transaction_type_global) if transaction_type_global else "",
                )
                if edi_msg.sender_id and edi_msg.receiver_id
                else None
            )
            partnership_id_str = route.get("trading_partner_id") if route else None

            for txn in transformed_txns:
                txn_type = txn.transaction_type
                gs_sender = txn.gs_sender_id
                gs_receiver = txn.gs_receiver_id

                if not gs_sender_global and gs_sender:
                    gs_sender_global = gs_sender
                    gs_receiver_global = gs_receiver

                import copy

                json_dict = copy.deepcopy(txn.payload) if txn.payload else {}
                if isinstance(json_dict, dict):
                    json_dict["transaction_type"] = txn_type
                business_metadata = extractor.extract(txn_type, json_dict)

                await self.uow.repository.save_edi_json(
                    trace_id=trace_id,
                    direction=MessageDirection.INBOUND.value,
                    partnership_id=partnership_id_str,
                    transaction_type=txn_type,
                    standard=standard,
                    sender_id=edi_msg.sender_id,
                    receiver_id=edi_msg.receiver_id,
                    gs_sender_id=gs_sender,
                    gs_receiver_id=gs_receiver,
                    business_metadata=business_metadata,
                    payload=json_dict,
                    status=MessageStatus.PARSED.value,
                    tenant_id=edi_msg.tenant_id,
                )
                json_payloads.append(json_dict)

            # Metadata to emit in event
            txn_type_for_parent = transformed_txns[0].transaction_type if transformed_txns else None

            # 3. Build the complete EDI Webhook envelope
            trading_partner_id = partnership_id_str

            webhook_url = None
            if route and route.get("webhook_id"):
                partner = await self.uow.repository.get_webhook(str(route.get("webhook_id")))
                if partner:
                    webhook_url = partner.get("url")

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
            await self.uow.repository.save_api_payload(
                trace_id=trace_id,
                direction=MessageDirection.OUTBOUND.value,
                payload=envelope.model_dump(),
                status=MessageStatus.PENDING_DELIVERY.value,
                transaction_type=standard,
                webhook_url=webhook_url,
            )

            # 4. Publish TRANSFORM_COMPLETED event
            transform_completed_key = str(
                uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:TRANSFORM_COMPLETED")
            )
            await self.uow.outbox.append_event(
                idempotency_key=transform_completed_key,
                event_type=PipelineEventType.TRANSFORM_COMPLETED.value,
                payload={
                    "trace_id": trace_id,
                    "direction": MessageDirection.INBOUND.value,
                    "gs_sender_id": gs_sender_global,
                    "gs_receiver_id": gs_receiver_global,
                    "transaction_type": txn_type_for_parent,
                },
            )

            await self.uow.commit()

        logger.info("compute_transform.completed", trace_id=trace_id)
