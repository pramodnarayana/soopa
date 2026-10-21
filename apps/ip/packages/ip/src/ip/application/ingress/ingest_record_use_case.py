"""Use case for capturing raw inbound payloads with sub-20ms response and zero data loss."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

import structlog
from ip.domain.constants import IpDomainIdPrefix
from ip.domain.models.inbound_record import InboundRecord
from ip.domain.types import JsonDict, JsonValue
from ip.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.ports.outbound.tiered_storage_port import TieredStoragePort
from seedwork.utils import generate_id

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IngestRecordCommand:
    """Command payload to ingest an external raw payload into Layer 1."""

    tenant_id: str
    connection_id: str
    stream_name: str
    payload: JsonDict | Sequence[JsonValue] | bytes
    headers: JsonDict = field(default_factory=dict)
    business_correlation_id: str | None = None
    business_trace_id: str | None = None


@dataclass(frozen=True)
class IngestRecordResultDTO:
    """Result returned immediately (<20ms) upon staging an inbound record."""

    record_id: str
    business_trace_id: str
    status: str = "ACCEPTED"
    payload_size_bytes: int = 0
    is_inlined: bool = True


class IngestRecordUseCase:
    """Ingestion Gateway (L1) coordinator persisting audit evidence and enqueuing outbox events."""

    def __init__(
        self,
        inbound_repo: InboundRecordRepositoryPort,
        tiered_storage: TieredStoragePort,
    ) -> None:
        self._inbound_repo = inbound_repo
        self._tiered_storage = tiered_storage

    async def execute(self, command: IngestRecordCommand) -> IngestRecordResultDTO:
        trace_id = command.business_trace_id or generate_id(IpDomainIdPrefix.TRACE)

        # 1. Normalize payload to raw bytes and optional parsed dict
        payload_bytes: bytes
        parsed_payload: JsonDict | None = None

        if isinstance(command.payload, bytes):
            payload_bytes = command.payload
            try:
                decoded = json.loads(payload_bytes.decode("utf-8"))
                if isinstance(decoded, dict):
                    parsed_payload = decoded
            except (json.JSONDecodeError, UnicodeDecodeError):
                parsed_payload = None
        else:
            payload_bytes = json.dumps(command.payload, separators=(",", ":")).encode("utf-8")
            if isinstance(command.payload, dict):
                parsed_payload = command.payload

        # 2. Evaluate Tiered Storage (<64KB inline vs >=64KB S3)
        storage_result = await self._tiered_storage.store(
            tenant_id=command.tenant_id,
            trace_id=trace_id,
            payload_bytes=payload_bytes,
            parsed_payload=parsed_payload,
        )

        # 3. Create InboundRecord aggregate root (emits InboundRecordCreatedEvent)
        record = InboundRecord.create(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream_name=command.stream_name,
            payload_bytes=payload_bytes,
            is_inlined=storage_result.is_inlined,
            raw_payload=storage_result.raw_payload,
            s3_key=storage_result.s3_key,
            headers=command.headers,
            business_correlation_id=command.business_correlation_id,
            business_trace_id=trace_id,
        )

        # 4. Save to Repository and drain domain events to Outbox
        await self._inbound_repo.save(record)

        logger.info(
            "inbound_record_ingested",
            record_id=record.id,
            business_trace_id=record.business_trace_id,
            tenant_id=record.tenant_id,
            connection_id=record.connection_id,
            stream_name=record.stream_name,
            payload_size_bytes=storage_result.payload_size_bytes,
            is_inlined=storage_result.is_inlined,
        )

        return IngestRecordResultDTO(
            record_id=record.id,
            business_trace_id=record.business_trace_id,
            status="ACCEPTED",
            payload_size_bytes=storage_result.payload_size_bytes,
            is_inlined=storage_result.is_inlined,
        )
