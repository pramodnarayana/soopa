import uuid

import structlog
from config.settings import AppSettings
from domain.direction import MessageDirection
from domain.events import PipelineEventType
from domain.status import MessageStatus

from pipeline.core.metadata_extractor import MetadataExtractorService
from pipeline.core.models import EdiWebhookPayload
from pipeline.ports.outbound.data_plane_unit_of_work_port import DataPlaneUnitOfWorkPort
from pipeline.ports.outbound.transformer_port import TransformerPort

logger = structlog.get_logger(__name__)


class InboundTransformUseCase:
    """
    Application Use Case for orchestrating inbound EDI to JSON transformation.
    """

    def __init__(
        self,
        uow: DataPlaneUnitOfWorkPort,
        transformer: TransformerPort,
        settings: AppSettings,
    ) -> None:
        self.uow = uow
        self.transformer = transformer
        self._settings = settings

    async def execute(self, trace_id: str) -> None:
        """Transforms an inbound X12 EDI payload to JSON."""
        logger.info("inbound_transform.started", trace_id=trace_id)

        async with self.uow:
            edi_msg = await self.uow.repository.get_edi_message(trace_id)
            if not edi_msg:
                raise ValueError(f"No EDI message found for trace_id={trace_id}")

            if not edi_msg.edi_data:
                raise ValueError(f"No EDI data found for trace_id={trace_id}")
            raw_payload = edi_msg.edi_data.encode("utf-8")

            # 2. Transform
            standard = edi_msg.format_standard or "X12"
            transaction_type = edi_msg.transaction_type or "UNKNOWN"

            if self._settings.enable_heavy_compute_queue:
                logger.info(
                    "inbound_transform.offloading_to_compute",
                    trace_id=trace_id,
                )
                compute_key = str(
                    uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:COMPUTE_TRANSFORM_EVENT")
                )
                await self.uow.outbox.append_event(
                    idempotency_key=compute_key,
                    event_type=PipelineEventType.COMPUTE_TRANSFORM_EVENT,
                    payload={
                        "trace_id": trace_id,
                        "direction": MessageDirection.INBOUND,
                        "standard": standard,
                        "transaction_type": transaction_type,
                    },
                )
                await self.uow.commit()
                return

            transformed_txns = await self.transformer.transform_edi_to_json(
                payload=raw_payload, standard=standard, transaction_type=transaction_type
            )
            if not transformed_txns:
                raise ValueError(f"Failed to transform EDI transaction {transaction_type}")

            # 3. Process each transaction
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
                    MessageDirection.INBOUND,
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

                json_dict = txn.payload

                # Embed transaction_type directly into the transaction JSON payload
                json_dict["transaction_type"] = txn_type

                business_metadata = extractor.extract(txn_type, json_dict)

                await self.uow.repository.save_edi_json(
                    trace_id=trace_id,
                    direction=MessageDirection.INBOUND,
                    partnership_id=None,
                    transaction_type=txn_type,
                    standard=standard,
                    sender_id=edi_msg.sender_id,
                    receiver_id=edi_msg.receiver_id,
                    gs_sender_id=gs_sender,
                    gs_receiver_id=gs_receiver,
                    business_metadata=business_metadata,
                    payload=json_dict,
                    status=MessageStatus.PARSED,
                    tenant_id=edi_msg.tenant_id,
                )

                json_payloads.append(json_dict)

            # Metadata to emit in event
            txn_type_for_parent = transformed_txns[0].transaction_type if transformed_txns else None

            # 5. Build the complete EDI Webhook envelope
            trading_partner_id = partnership_id_str

            webhook_url = None
            if route and route.get("webhook_id"):
                partner = await self.uow.repository.get_webhook(str(route.get("webhook_id")))
                if partner:
                    webhook_url = partner.get("url")

            envelope = EdiWebhookPayload.build(
                trace_id=trace_id,
                direction=MessageDirection.INBOUND,
                sender_id=edi_msg.sender_id,
                receiver_id=edi_msg.receiver_id,
                trading_partner_id=trading_partner_id,
                format_standard=standard,
                transactions=json_payloads,
            )

            # Save ApiGateway to DB as a single webhook delivery containing the complete envelope
            await self.uow.repository.save_api_payload(
                trace_id=trace_id,
                direction=MessageDirection.OUTBOUND,
                payload=envelope.model_dump(),
                status=MessageStatus.PENDING_DELIVERY,
                transaction_type=standard,
                webhook_url=webhook_url,
            )

            # 6. Publish TRANSFORM_COMPLETED event
            transform_completed_key = str(
                uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:TRANSFORM_COMPLETED")
            )
            await self.uow.outbox.append_event(
                idempotency_key=transform_completed_key,
                event_type=PipelineEventType.TRANSFORM_COMPLETED,
                payload={
                    "trace_id": trace_id,
                    "direction": MessageDirection.INBOUND,
                    "gs_sender_id": gs_sender_global,
                    "gs_receiver_id": gs_receiver_global,
                    "transaction_type": txn_type_for_parent,
                },
            )

            await self.uow.commit()

        logger.info("inbound_transform.completed", trace_id=trace_id)
