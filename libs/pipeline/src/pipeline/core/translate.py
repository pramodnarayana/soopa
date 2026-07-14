import logging
import uuid

from config.settings import get_settings
from domain.direction import MessageDirection
from domain.events import PipelineEventType
from domain.status import MessageStatus
from pipeline.ports.repository import RepositoryPort
from pipeline.ports.transformer import TransformerPort

logger = logging.getLogger(__name__)


class TranslationService:
    """
    Pure domain service for orchestrating EDI translation.
    Follows Hexagonal Architecture: takes ports, knows nothing of SQS/DB details.
    """

    def __init__(
        self,
        transformer: TransformerPort,
        repository: RepositoryPort,
    ) -> None:
        self.transformer = transformer
        self.repository = repository

    async def translate(self, trace_id: str, direction: MessageDirection) -> None:
        """
        Translates an incoming message (EDI or JSON) into its target format.
        """
        logger.info(f"Starting translation pipeline for trace_id={trace_id} direction={direction}")

        if direction == MessageDirection.OUTBOUND:
            await self._translate_json_to_edi(trace_id)
        else:
            await self._translate_edi_to_json(trace_id)

    async def _translate_json_to_edi(self, trace_id: str) -> None:
        """Translates an outbound JSON payload to X12 EDI."""
        edi_json = await self.repository.get_edi_json(trace_id)
        if not edi_json:
            raise ValueError(f"No EdiJson record found for trace_id={trace_id}")

        outbound_route_id = str(edi_json.outbound_route_id) if edi_json.outbound_route_id else None
        tenant_id = edi_json.tenant_id

        business_metadata = edi_json.business_metadata or {}
        routing_meta = business_metadata.get("_routing") or {}
        trading_partner_id = routing_meta.get("trading_partner_id")

        if outbound_route_id:
            route_config = await self.repository.get_outbound_edi_header_by_route_or_partner(
                route_id=outbound_route_id
            )
            # Also get the route to link to EdiMessage
            outbound_route = await self.repository.get_outbound_route(outbound_route_id)
        else:
            if not trading_partner_id or not tenant_id:
                raise ValueError(
                    f"No routing info available (trading_partner_id/tenant_id) for trace_id={trace_id}"
                )
            route_config = await self.repository.get_outbound_edi_header_by_route_or_partner(
                trading_partner_id=trading_partner_id, tenant_id=tenant_id
            )
            # Get the route to link to EdiMessage
            outbound_route = await self.repository.get_outbound_route_by_trading_partner_id(
                trading_partner_id=trading_partner_id, tenant_id=tenant_id
            )
            if outbound_route:
                outbound_route_id = outbound_route.get("id")

        if not route_config or not outbound_route:
            raise ValueError(
                f"Outbound route/header configuration not found for trace_id={trace_id}"
            )

        json_payload = edi_json.payload
        if not json_payload:
            raise ValueError(f"Payload is missing for trace_id={trace_id}")

        standard = route_config.get("default_standard", "X12")
        route_txn_type = route_config.get("transaction_type")
        if route_txn_type == "*":
            route_txn_type = None

        transaction_type = route_txn_type or edi_json.transaction_type or "UNKNOWN"

        # Ensure the resolved transaction type is used by the envelope builders
        route_config["transaction_type"] = transaction_type

        # Ensure environment is present for the transformer
        if "environment" not in route_config:
            settings = get_settings()
            route_config["environment"] = settings.edi_environment

        raw_edi_bytes = await self.transformer.translate_json_to_edi(
            payload=json_payload,
            standard=standard,
            transaction_type=transaction_type,
            route_config=route_config,
        )

        edi_str = raw_edi_bytes.decode("utf-8")

        connection_type = route_config.get("connection_type", "UNKNOWN")
        if connection_type == "UNKNOWN" and outbound_route:
            if outbound_route.get("as2_partner_id"):
                connection_type = "AS2"
            elif outbound_route.get("sftp_partner_id"):
                connection_type = "SFTP"

        await self.repository.save_edi_message(
            trace_id=trace_id,
            direction=MessageDirection.OUTBOUND,
            edi_data=edi_str,
            format_standard=standard,
            transaction_type=transaction_type,
            status=MessageStatus.PENDING_DELIVERY,
            connection_type=connection_type,
            sender_id=route_config.get("isa_sender_id"),
            receiver_id=route_config.get("isa_receiver_id"),
            gs_sender_id=route_config.get("gs_sender_id"),
            gs_receiver_id=route_config.get("gs_receiver_id"),
            outbound_route_id=outbound_route_id,
            tenant_id=edi_json.tenant_id,
        )

        transform_completed_key = str(
            uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:TRANSFORM_COMPLETED")
        )
        await self.repository.publish_outbox_event(
            idempotency_key=transform_completed_key,
            event_type=PipelineEventType.TRANSFORM_COMPLETED,
            payload={
                "trace_id": trace_id,
                "direction": MessageDirection.OUTBOUND,
                "outbound_route_id": outbound_route_id,
                "standard": standard,
                "isa_sender_id": route_config.get("isa_sender_id"),
                "isa_receiver_id": route_config.get("isa_receiver_id"),
                "gs_sender_id": route_config.get("gs_sender_id"),
                "gs_receiver_id": route_config.get("gs_receiver_id"),
            },
        )
        logger.info(f"Successfully transformed JSON to EDI for trace_id={trace_id}")

    async def _translate_edi_to_json(self, trace_id: str) -> None:
        """Translates an inbound X12 EDI payload to JSON."""
        edi_msg = await self.repository.get_edi_message(trace_id)
        if not edi_msg:
            raise ValueError(f"No EDI message found for trace_id={trace_id}")

        if not edi_msg.edi_data:
            raise ValueError(f"No EDI data found for trace_id={trace_id}")
        raw_payload = edi_msg.edi_data.encode("utf-8")

        # 2. Translate
        standard = edi_msg.format_standard or "X12"
        transaction_type = edi_msg.transaction_type or "UNKNOWN"
        translated_txns = await self.transformer.translate_edi_to_json(
            payload=raw_payload, standard=standard, transaction_type=transaction_type
        )
        if not translated_txns:
            raise ValueError(f"Failed to translate EDI transaction {transaction_type}")

        # 3. Process each transaction
        from pipeline.core.metadata_extractor import MetadataExtractorService

        extractor = MetadataExtractorService()

        json_payloads = []
        gs_sender_global = None
        gs_receiver_global = None

        sender_id = edi_msg.sender_id
        receiver_id = edi_msg.receiver_id
        partnership_id_str = None

        for txn in translated_txns:
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

            await self.repository.save_edi_json(
                trace_id=trace_id,
                direction=MessageDirection.INBOUND,
                partnership_id=partnership_id_str,
                transaction_type=txn_type,
                standard=standard,
                sender_id=sender_id,
                receiver_id=receiver_id,
                gs_sender_id=gs_sender,
                gs_receiver_id=gs_receiver,
                business_metadata=business_metadata,
                payload=json_dict,
                status=MessageStatus.PARSED,
                tenant_id=edi_msg.tenant_id,
            )

            json_payloads.append(json_dict)

        # Metadata to emit in event
        txn_type_for_parent = translated_txns[0].transaction_type if translated_txns else None

        # 5. Build the complete EDI Webhook envelope
        from pipeline.core.models import EdiWebhookPayload

        sender_global = edi_msg.sender_id
        receiver_global = edi_msg.receiver_id
        transaction_type_global = (
            translated_txns[0].transaction_type if translated_txns else edi_msg.transaction_type
        )
        route = (
            await self.repository.get_route(
                MessageDirection.INBOUND,
                str(sender_global),
                str(receiver_global),
                str(transaction_type_global) if transaction_type_global else "",
            )
            if sender_global and receiver_global
            else None
        )
        trading_partner_id = route.get("trading_partner_id") if route else None

        webhook_url = None
        if route and route.get("webhook_id"):
            partner = await self.repository.get_webhook(str(route.get("webhook_id")))
            if partner:
                webhook_url = partner.get("url")

        envelope = EdiWebhookPayload.build(
            trace_id=trace_id,
            direction=MessageDirection.INBOUND,
            sender_id=sender_global,
            receiver_id=receiver_global,
            trading_partner_id=trading_partner_id,
            format_standard=standard,
            transactions=json_payloads,
        )

        # Save ApiGateway to DB as a single webhook delivery containing the complete envelope
        await self.repository.save_api_payload(
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
        await self.repository.publish_outbox_event(
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
        logger.info(f"Successfully transformed EDI to JSON for trace_id={trace_id}")
