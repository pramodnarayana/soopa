import structlog
from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import JsonValue
from seedwork.utils import generate_id

from edi.application.dtos import ProcessApiEdiJsonCommand
from edi.core.pipeline.metadata_extractor import MetadataExtractorService
from edi.domain.constants import TransactionDirection
from edi.domain.events import TransformRequestedEvent
from edi.domain.models.base import Direction, RecordStatus
from edi.domain.models.transactions import EdiJsonDomainModel
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

                # We know first_payload is expected to be a dict here for transaction_type extraction
                if isinstance(first_payload, dict):
                    tt_val = first_payload.get("transaction_type")
                    if isinstance(tt_val, str):
                        transaction_type = tt_val

                    if not transaction_type:
                        heading = first_payload.get("heading")
                        if isinstance(heading, dict):
                            for key in heading:
                                if isinstance(key, str) and key.startswith(
                                    "transaction_set_header_ST"
                                ):
                                    inner = heading[key]
                                    if isinstance(inner, dict):
                                        val = inner.get("transaction_set_identifier_code")
                                        if isinstance(val, str):
                                            transaction_type = val
                                    break
                    if not transaction_type:
                        st = first_payload.get("ST")
                        if isinstance(st, dict):
                            val = st.get("ST01")
                            if isinstance(val, str):
                                transaction_type = val
            business_metadata = self.extractor.extract(transaction_type or "", command.payload)

            business_metadata["_routing"] = {"trading_partner_id": command.trading_partner_id}

            # 2. Create Trace ID
            trace_id = generate_id(SystemIdPrefix.GENERIC)
            logger.info("trace_id_generated", trace_id=trace_id)

            if isinstance(command.payload, list):
                domain_payload: JsonValue = [item for item in command.payload]
            else:
                domain_payload = command.payload

            # 3. Instantiate Domain Model and record event
            edi_json_aggregate = EdiJsonDomainModel(
                id=generate_id(SystemIdPrefix.GENERIC),
                tenant_id=command.tenant_id,
                trace_id=trace_id,
                direction=Direction.OUTBOUND,
                transaction_type=transaction_type,
                business_metadata=business_metadata,
                payload=domain_payload,
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
