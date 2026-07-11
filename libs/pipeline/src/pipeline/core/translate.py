import json
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
        standard = edi_msg.get("format_standard", "X12")
        transaction_type = edi_msg.get("transaction_type", "UNKNOWN")
        json_dict = await self.transformer.translate_edi_to_json(
            payload=raw_payload, standard=standard, transaction_type=transaction_type
        )

        json.dumps(json_dict).encode("utf-8")

        # 3. Extract Business Metadata
        from pipeline.core.metadata_extractor import MetadataExtractorService

        extractor = MetadataExtractorService()
        business_metadata = extractor.extract(transaction_type, json_dict)

        # 4. Save to EdiJson
        partnership_id_str = edi_msg.get("partnership_id")
        if isinstance(partnership_id_str, uuid.UUID):
            partnership_id_str = str(partnership_id_str)

        await self.repository.save_edi_json(
            trace_id=trace_id,
            direction="INBOUND",
            partnership_id=partnership_id_str,
            transaction_type=transaction_type,
            standard=standard,
            sender_id=edi_msg.get("sender_id"),
            receiver_id=edi_msg.get("receiver_id"),
            business_metadata=business_metadata,
            payload=json_dict,
            status="PENDING_DELIVERY",
            tenant_id=edi_msg.get("tenant_id"),
        )

        edi_msg.get("tenant_id")

        # 5. Save ApiGateway to DB
        await self.repository.save_api_payload(
            trace_id=trace_id,
            direction="OUTBOUND",
            payload=json_dict,
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
