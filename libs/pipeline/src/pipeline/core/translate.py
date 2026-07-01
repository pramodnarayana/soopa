import json
import logging
import uuid

from pipeline.ports.repository import RepositoryPort
from pipeline.ports.storage import StoragePort
from pipeline.ports.transformer import TransformerPort

logger = logging.getLogger(__name__)


class TranslationService:
    """
    Pure domain service for orchestrating EDI translation.
    Follows Hexagonal Architecture: takes ports, knows nothing of SQS/DB details.
    """

    def __init__(
        self,
        storage: StoragePort,
        transformer: TransformerPort,
        repository: RepositoryPort,
    ) -> None:
        self.storage = storage
        self.transformer = transformer
        self.repository = repository

    async def translate(self, trace_id: str) -> None:
        """
        Translates an incoming message (EDI or JSON) into its target format.
        """
        logger.info(f"Starting translation pipeline for trace_id={trace_id}")

        edi_msg = await self.repository.get_edi_message(trace_id)
        if not edi_msg:
            raise ValueError(f"No EDI message found for trace_id={trace_id}")

        # 1. Download payload
        s3_uri = edi_msg["edi_data"]
        raw_payload = await self.storage.download(s3_uri)

        # 2. Translate
        standard = edi_msg.get("format_standard", "X12")
        transaction_type = edi_msg.get("transaction_type", "UNKNOWN")
        json_dict = await self.transformer.translate_edi_to_json(
            payload=raw_payload, standard=standard, transaction_type=transaction_type
        )

        json_bytes = json.dumps(json_dict).encode("utf-8")

        tenant_id = edi_msg.get("tenant_id")

        # 3. Upload translated payload
        new_s3_uri = await self.storage.upload(
            payload=json_bytes,
            key_prefix=f"tenants/{tenant_id}/api_gateway/{trace_id}",
            file_name="translated.json",
        )

        # 4. Save ApiGateway to DB
        await self.repository.save_api_payload(
            trace_id=trace_id,
            direction="OUTBOUND",
            s3_uri=new_s3_uri,
            status="PENDING_DELIVERY",
        )

        # 5. Publish DELIVER event with a stable idempotency key derived from trace_id
        deliver_idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{trace_id}:DELIVER"))
        await self.repository.publish_outbox_event(
            idempotency_key=deliver_idempotency_key,
            event_type="DELIVER",
            payload={"trace_id": trace_id},
        )

        # 6. Update EDI message status
        await self.repository.update_edi_message_status(trace_id, "TRANSLATED")
        logger.info(f"Successfully translated trace_id={trace_id}")
