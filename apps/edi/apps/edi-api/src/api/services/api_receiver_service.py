import logging
import uuid
from typing import Any
from uuid import UUID

from pipeline.core.metadata_extractor import MetadataExtractorService

from api.core.uow import UnitOfWork

logger = logging.getLogger(__name__)


class ApiReceiverService:
    """
    Application Service (Use Case Layer) for handling outbound API requests.
    Strictly follows Single Responsibility Principle and encapsulates business logic.
    """

    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        self.extractor = MetadataExtractorService()

    async def process_api_edi_json(
        self,
        tenant_id: str,
        trading_partner_id: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        transaction_type: str | None = None,
    ) -> UUID:
        """
        Orchestrates the outbound API flow:
        1. Validate Partnership by trading_partner_id.
        2. Extract Business Metadata.
        3. Save to EdiJson.
        4. Drop Outbox event for Worker to transform.

        Returns:
            UUID: The generated trace_id for tracking.
        """
        async with self.uow:
            logger.info(f"Received outbound JSON for partner: {trading_partner_id}")

            # 1. Resolve transaction_type from payload if not provided explicitly
            if not transaction_type:
                first_payload = (
                    payload[0]
                    if isinstance(payload, list) and payload
                    else (payload if isinstance(payload, dict) else {})
                )
                transaction_type = first_payload.get("transaction_type")
                if not transaction_type:
                    heading = first_payload.get("heading", {})
                    for key in heading:
                        if key.startswith("transaction_set_header_ST"):
                            transaction_type = heading[key].get("transaction_set_identifier_code")
                            break
                if not transaction_type:
                    # Try ST segment directly (for raw transaction payloads)
                    st = first_payload.get("ST", {})
                    if st:
                        transaction_type = st.get("ST01")

            business_metadata: dict[str, Any] = {}
            if isinstance(payload, dict):
                business_metadata = self.extractor.extract(transaction_type or "", payload)
            elif isinstance(payload, list) and len(payload) > 0:
                extracted_list = [
                    self.extractor.extract(transaction_type or "", item) for item in payload
                ]
                for extracted in extracted_list:
                    for k, v in extracted.items():
                        if k not in business_metadata:
                            business_metadata[k] = []
                        # Avoid duplicates
                        if v not in business_metadata[k]:
                            business_metadata[k].append(v)

                # Flatten single-item lists for backward compatibility
                for k, v in business_metadata.items():
                    if isinstance(v, list) and len(v) == 1:
                        business_metadata[k] = v[0]

            business_metadata["_routing"] = {"trading_partner_id": trading_partner_id}

            # 2. Create Trace ID
            trace_id = uuid.uuid4()
            logger.info(f"Generated Trace ID: {trace_id}")

            # 3. Save EdiJson (Status: RECEIVED)
            # We defer ALL routing and translation config logic to the Worker.
            edi_json_payload = {
                "trace_id": trace_id,
                "direction": "OUTBOUND",
                "transaction_type": transaction_type,
                "business_metadata": business_metadata,
                "payload": payload,
                "status": "RECEIVED",
            }
            await self.uow.transactions.create_edi_json(
                tenant_id=tenant_id, payload=edi_json_payload
            )

            # 5. Drop Outbox event for Worker to transform
            from domain.events import PipelineEventType

            await self.uow.data_plane_outbox.publish_outbox_event(
                tenant_id=tenant_id,
                event_type=PipelineEventType.TRANSFORM_EVENT,
                payload={
                    "trace_id": str(trace_id),
                    "tenant_id": tenant_id,
                    "trading_partner_id": trading_partner_id,
                    "direction": "OUTBOUND",
                },
                idempotency_key=trace_id,
            )

            await self.uow.commit()
            return trace_id
