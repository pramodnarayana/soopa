from dataclasses import dataclass

import structlog
from seedwork.domain.types import JsonValue
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id

from edi.core.pipeline.metadata_extractor import MetadataExtractorService
from edi.core.pipeline.transaction_type_resolver import TransactionTypeResolver
from edi.domain.enums import EdiDirection
from edi.domain.events import TransformRequestedEvent
from edi.domain.exceptions import IdempotencyConflictError
from edi.domain.models.base import Direction, RecordStatus
from edi.domain.models.transactions import EdiJsonDomainModel
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ProcessApiEdiJsonCommand:
    tenant_id: str
    trading_partner_id: str
    payload: JsonValue
    transaction_type: str | None = None
    idempotency_key: str | None = None


class ProcessApiEdiJsonUseCase:
    """
    Application Service (Use Case Layer) for handling outbound API requests.
    Strictly follows Single Responsibility Principle and encapsulates business logic.
    """

    def __init__(self, uow: DataPlaneUnitOfWorkPort) -> None:
        self.uow = uow
        self.extractor = MetadataExtractorService()

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

            if command.idempotency_key:
                existing = await self.uow.transactions.get_edi_json_by_idempotency_key(
                    command.tenant_id, command.idempotency_key
                )
                if existing:
                    logger.info(
                        "idempotency_key_hit",
                        trace_id=existing.trace_id,
                        idempotency_key=command.idempotency_key,
                    )
                    return existing.trace_id

            # 1. Resolve transaction_type from payload if not provided explicitly.
            # Shared domain service ensures the same extraction heuristics are used
            # at ingestion time and at transform-dispatch time.
            transaction_type = TransactionTypeResolver.resolve(
                explicit_type=command.transaction_type,
                payload=command.payload,
            )
            business_metadata = self.extractor.extract(transaction_type or "", command.payload)

            business_metadata["_routing"] = {"trading_partner_id": command.trading_partner_id}
            if command.idempotency_key:
                business_metadata["_idempotency_key"] = command.idempotency_key

            # 2. Create Trace ID
            trace_id = generate_id(SystemIdPrefix.TRACE)
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
                trading_partner_id=command.trading_partner_id,
                transaction_type=transaction_type,
                business_metadata=business_metadata,
                payload=domain_payload,
                status=RecordStatus.RECEIVED,
            )

            # 4. Queue the transform atomically through the transaction aggregate
            event_kwargs = {
                "trace_id": str(trace_id),
                "tenant_id": command.tenant_id,
                "trading_partner_id": command.trading_partner_id,
                "direction": EdiDirection.OUTBOUND.value,
            }
            if command.idempotency_key:
                event_kwargs["idempotency_key"] = command.idempotency_key

            edi_json_aggregate.add_domain_event(TransformRequestedEvent(**event_kwargs))

            # 5. Save aggregate and let Repository drain events to the outbox atomically.
            # If a concurrent request with the same idempotency key already committed,
            # the DB unique constraint will raise a conflict which we catch and resolve
            # by looking up the already-persisted record.
            try:
                await self.uow.transactions.save_json(edi_json_aggregate)
                await self.uow.commit()
            except IdempotencyConflictError:
                if command.idempotency_key:
                    existing = await self.uow.transactions.get_edi_json_by_idempotency_key(
                        command.tenant_id, command.idempotency_key
                    )
                    if existing:
                        logger.info(
                            "idempotency_key_conflict_resolved",
                            trace_id=existing.trace_id,
                            idempotency_key=command.idempotency_key,
                        )
                        return existing.trace_id
                raise

            return trace_id
