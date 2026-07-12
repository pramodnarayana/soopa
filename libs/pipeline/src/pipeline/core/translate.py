import logging
import uuid

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

    async def translate(self, trace_id: str, event_type: str = "edi_message.received") -> None:
        """
        Translates an incoming message (EDI or JSON) into its target format.
        """
        logger.info(
            f"Starting translation pipeline for trace_id={trace_id} event_type={event_type}"
        )

        if event_type == "json.received":
            await self._translate_json_to_edi(trace_id)
        else:
            # Default to EDI to JSON for edi_message.received or TRANSLATE
            await self._translate_edi_to_json(trace_id)

    async def _translate_json_to_edi(self, trace_id: str) -> None:
        """Translates an outbound JSON payload to X12 EDI."""
        edi_json = await self.repository.get_edi_json(trace_id)
        if not edi_json:
            raise ValueError(f"No EdiJson record found for trace_id={trace_id}")

        outbound_route_id = edi_json.get("outbound_route_id")
        if not outbound_route_id:
            raise ValueError(f"No outbound_route_id set for trace_id={trace_id}")

        route_config = await self.repository.get_outbound_route(outbound_route_id)
        if not route_config:
            raise ValueError(f"Outbound route {outbound_route_id} not found")

        json_payload = edi_json["payload"]
        standard = route_config.get("default_standard", "X12")
        transaction_type = route_config.get(
            "transaction_type", edi_json.get("transaction_type", "UNKNOWN")
        )

        raw_edi_bytes = await self.transformer.translate_json_to_edi(
            payload=json_payload,
            standard=standard,
            transaction_type=transaction_type,
            route_config=route_config,
        )

        edi_str = raw_edi_bytes.decode("utf-8")

        await self.repository.save_edi_message(
            trace_id=trace_id,
            direction="OUTBOUND",
            edi_data=edi_str,
            format_standard=standard,
            transaction_type=transaction_type,
            status="PENDING_DELIVERY",
            connection_type=route_config.get("connection_type", "UNKNOWN"),
            sender_id=route_config.get("isa_sender_id"),
            receiver_id=route_config.get("isa_receiver_id"),
            gs_sender_id=route_config.get("gs_sender_id"),
            gs_receiver_id=route_config.get("gs_receiver_id"),
            outbound_route_id=outbound_route_id,
            tenant_id=edi_json.get("tenant_id"),
        )

        await self.repository.update_edi_json_status(trace_id, "TRANSLATED")

        deliver_idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:DELIVER"))
        await self.repository.publish_outbox_event(
            idempotency_key=deliver_idempotency_key,
            event_type="DELIVER",
            payload={"trace_id": trace_id},
        )
        logger.info(f"Successfully translated JSON to EDI for trace_id={trace_id}")

    async def _translate_edi_to_json(self, trace_id: str) -> None:
        """Translates an inbound X12 EDI payload to JSON."""
        edi_msg = await self.repository.get_edi_message(trace_id)
        if not edi_msg:
            raise ValueError(f"No EDI message found for trace_id={trace_id}")

        # 1. Fetch raw payload from repository
        raw_payload = edi_msg["edi_data"].encode("utf-8")

        # 2. Translate
        standard = edi_msg.get("format_standard") or "X12"
        transaction_type = edi_msg.get("transaction_type") or "UNKNOWN"
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

        sender_id = edi_msg.get("sender_id")
        receiver_id = edi_msg.get("receiver_id")
        partnership_id_str = edi_msg.get("partnership_id")
        if isinstance(partnership_id_str, uuid.UUID):
            partnership_id_str = str(partnership_id_str)

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
                direction="INBOUND",
                partnership_id=partnership_id_str,
                transaction_type=txn_type,
                standard=standard,
                sender_id=sender_id,
                receiver_id=receiver_id,
                gs_sender_id=gs_sender,
                gs_receiver_id=gs_receiver,
                business_metadata=business_metadata,
                payload=json_dict,
                status="PENDING_DELIVERY",
                tenant_id=edi_msg.get("tenant_id"),
            )

            json_payloads.append(json_dict)

        # 3.1 Update GS headers on the parent edi_message (using the first transaction's envelope)
        if gs_sender_global and gs_receiver_global:
            await self.repository.update_edi_message_gs_headers(
                trace_id, gs_sender_global, gs_receiver_global
            )

        # 5. Build the complete EDI Webhook envelope
        from pipeline.core.models import EdiWebhookPayload

        # Lookup trading_partner_id from the route for the batch
        sender_global = edi_msg.get("sender_id")
        receiver_global = edi_msg.get("receiver_id")
        transaction_type_global = (
            translated_txns[0].transaction_type
            if translated_txns
            else edi_msg.get("transaction_type")
        )
        route = (
            await self.repository.get_route(
                "INBOUND",
                str(sender_global),
                str(receiver_global),
                str(transaction_type_global) if transaction_type_global else "",
            )
            if sender_global and receiver_global
            else None
        )
        trading_partner_id = route.get("trading_partner_id") if route else None

        envelope = EdiWebhookPayload.build(
            trace_id=trace_id,
            direction="INBOUND",
            sender_id=sender_global,
            receiver_id=receiver_global,
            trading_partner_id=trading_partner_id,
            format_standard=standard,
            transactions=json_payloads,
        )

        # Save ApiGateway to DB as a single webhook delivery containing the complete envelope
        await self.repository.save_api_payload(
            trace_id=trace_id,
            direction="OUTBOUND",
            payload=envelope.model_dump(),
            status="PENDING_DELIVERY",
        )

        # 6. Publish DELIVER event with a stable idempotency key derived from trace_id
        deliver_idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:DELIVER"))
        await self.repository.publish_outbox_event(
            idempotency_key=deliver_idempotency_key,
            event_type="DELIVER",
            payload={"trace_id": trace_id},
        )

        # 7. Update EDI message status
        await self.repository.update_edi_message_status(trace_id, "TRANSLATED")
        logger.info(f"Successfully translated EDI to JSON for trace_id={trace_id}")
