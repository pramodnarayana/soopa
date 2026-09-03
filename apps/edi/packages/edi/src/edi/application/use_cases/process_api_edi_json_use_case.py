from collections.abc import Mapping

import structlog
from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import JsonValue
from seedwork.utils import generate_id

from edi.application.dtos import ProcessApiEdiJsonCommand
from edi.core.pipeline.metadata_extractor import MetadataExtractorService
from edi.domain.enums import EdiDirection
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

    @staticmethod
    def _extract_from_flat_field(payload_dict: Mapping[str, object]) -> str | None:
        """Extract transaction type from the flat `transaction_type` field."""
        tt_val = payload_dict.get("transaction_type")
        return tt_val if isinstance(tt_val, str) else None

    @staticmethod
    def _extract_from_heading(payload_dict: Mapping[str, object]) -> str | None:
        """Extract transaction type from EDI JSON `heading` structure."""
        heading = payload_dict.get("heading")
        if not isinstance(heading, dict):
            return None
        for key in heading:
            if isinstance(key, str) and key.startswith("transaction_set_header_ST"):
                inner = heading[key]
                if isinstance(inner, dict):
                    val = inner.get("transaction_set_identifier_code")
                    if isinstance(val, str):
                        return val
                break
        return None

    @staticmethod
    def _extract_from_st_segment(payload_dict: Mapping[str, object]) -> str | None:
        """Extract transaction type from the raw `ST` segment shorthand."""
        st = payload_dict.get("ST")
        if isinstance(st, dict):
            val = st.get("ST01")
            if isinstance(val, str):
                return val
        return None

    def _resolve_transaction_type(
        self, transaction_type: str | None, payload: JsonValue
    ) -> str | None:
        if transaction_type:
            return transaction_type

        first_payload = (
            payload[0]
            if isinstance(payload, list) and payload
            else (payload if isinstance(payload, dict) else {})
        )

        if not isinstance(first_payload, dict):
            return None

        return (
            self._extract_from_flat_field(first_payload)
            or self._extract_from_heading(first_payload)
            or self._extract_from_st_segment(first_payload)
        )

    async def process_api_edi_json(
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
            transaction_type = self._resolve_transaction_type(
                command.transaction_type, command.payload
            )
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
                    direction=EdiDirection.OUTBOUND.value,
                )
            )

            # 5. Save aggregate and let Repository drain events to the outbox automatically
            await self.uow.transactions.save_json(edi_json_aggregate)

            await self.uow.commit()
            return trace_id
