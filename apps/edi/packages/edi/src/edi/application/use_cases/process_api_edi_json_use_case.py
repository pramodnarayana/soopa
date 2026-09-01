from typing import Any

import structlog
from seedwork import SystemIdPrefix, generate_id

from edi.application.dto import ProcessApiEdiJsonCommand
from edi.core.pipeline.metadata_extractor import MetadataExtractorService
from edi.domain.constants import TransactionDirection
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class ProcessApiEdiJsonUseCase:
    """
    Application Service (Use Case Layer) for handling outbound API requests.
    Strictly follows Single Responsibility Principle and encapsulates business logic.
    """

    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow
        self.extractor = MetadataExtractorService()

    async def process_api_edi_json(  # noqa: C901
        self,
        command: ProcessApiEdiJsonCommand,
    ) -> str:
        """
        Orchestrates the outbound API flow:
        1. Validate Partnership by trading_partner_id.
        2. Extract Business Metadata.
        3. Save to EdiJson.
        4. Drop Outbox event for Worker to transform.

        Returns:
            str: The generated trace_id for tracking.
        """
        async with self.uow:
            logger.info(
                "outbound_json_received",
                trading_partner_id=command.trading_partner_id,
                tenant_id=command.tenant_id,
            )

            # 1. Resolve transaction_type from payload if not provided explicitly
            transaction_type = command.transaction_type
            if not transaction_type:
                first_payload = (
                    command.payload[0]
                    if isinstance(command.payload, list) and command.payload
                    else (command.payload if isinstance(command.payload, dict) else {})
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
            if isinstance(command.payload, dict):
                business_metadata = self.extractor.extract(transaction_type or "", command.payload)
            elif isinstance(command.payload, list) and len(command.payload) > 0:
                extracted_list = [
                    self.extractor.extract(transaction_type or "", item) for item in command.payload
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

            business_metadata["_routing"] = {"trading_partner_id": command.trading_partner_id}

            # 2. Create Trace ID
            trace_id = generate_id(SystemIdPrefix.GENERIC)
            logger.info("trace_id_generated", trace_id=trace_id)

            from edi.domain.events import TransformRequestedEvent
            from edi.domain.models.base import Direction, RecordStatus
            from edi.domain.models.transactions import EdiJsonDomainModel

            # 3. Instantiate Domain Model and record event
            edi_json_aggregate = EdiJsonDomainModel(
                id=generate_id(SystemIdPrefix.GENERIC),
                tenant_id=command.tenant_id,
                trace_id=trace_id,
                direction=Direction.OUTBOUND,
                transaction_type=transaction_type,
                business_metadata=business_metadata,
                payload=command.payload,
                status=RecordStatus.RECEIVED,
            )

            # 4. Queue the transform atomically through the transaction aggregate
            edi_json_aggregate.add_domain_event(
                TransformRequestedEvent(
                    trace_id=str(trace_id),
                    tenant_id=command.tenant_id,
                    trading_partner_id=command.trading_partner_id,
                    direction=TransactionDirection.OUTBOUND.value,
                )
            )

            # 5. Save aggregate and let Repository drain events to the outbox automatically
            await self.uow.transactions.save_json(edi_json_aggregate)

            await self.uow.commit()
            return trace_id
