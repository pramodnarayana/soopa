"""Use case for capturing raw inbound payloads with sub-20ms response and zero data loss."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field

import structlog
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from ip.engine.domain.enums import IngestionMode
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IngestRecordCommand:
    """Command payload to ingest an external raw payload into Layer 1."""

    tenant_id: str
    connection_id: str
    stream_name: str
    payload: JsonDict | Sequence[JsonValue] | bytes
    app_id: str = ""
    ingestion_mode: IngestionMode = IngestionMode.PUSH_FULL
    sync_run_id: str | None = None
    generation_id: int | None = None
    external_event_id: str | None = None
    headers: JsonDict = field(default_factory=dict)
    response_status_code: int | None = None
    response_body: JsonDict | None = None
    duration_ms: int | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0


@dataclass(frozen=True)
class IngestRecordResultDTO:
    """Result returned immediately (<20ms) upon staging an inbound record."""

    record_id: str
    trace_id: str
    status: str = "ACCEPTED"
    payload_size_bytes: int = 0
    is_inlined: bool = True


class IngestRecordUseCase:
    """Ingestion Gateway (L1) coordinator persisting audit evidence and enqueuing outbox events inside a Data Plane UoW."""

    def __init__(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        tiered_storage: TieredStoragePort,
    ) -> None:
        self._uow = uow
        self._tiered_storage = tiered_storage

    async def execute(self, command: IngestRecordCommand) -> IngestRecordResultDTO:
        trace_id = command.trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)

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

        # 3. Create InboundRecord traced aggregate root (emits InboundRecordCreatedEvent & IpTraceEvent)
        record = InboundRecord.create(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            app_id=command.app_id,
            stream_name=command.stream_name,
            payload_bytes=payload_bytes,
            is_inlined=storage_result.is_inlined,
            request_body=storage_result.raw_payload,
            request_s3_key=storage_result.s3_key,
            request_headers=command.headers,
            response_status_code=command.response_status_code or 202,
            response_body=command.response_body,
            duration_ms=command.duration_ms,
            correlation_id=command.correlation_id,
            trace_id=trace_id,
            parent_trace_id=command.parent_trace_id,
            original_trace_id=command.original_trace_id,
            replay_count=command.replay_count,
            ingestion_mode=command.ingestion_mode,
            sync_run_id=command.sync_run_id,
            generation_id=command.generation_id,
            external_event_id=command.external_event_id,
        )

        # 4. Save to Repository inside DataPlaneUnitOfWork and commit atomically
        async with self._uow:
            await self._uow.inbound_records.save(record)
            await self._uow.commit()

        logger.info(
            "inbound_record_ingested",
            record_id=record.id,
            trace_id=record.trace_id,
            tenant_id=record.tenant_id,
            connection_id=record.connection_id,
            stream_name=record.stream_name,
            payload_size_bytes=storage_result.payload_size_bytes,
            is_inlined=storage_result.is_inlined,
        )

        return IngestRecordResultDTO(
            record_id=record.id,
            trace_id=record.trace_id,
            status="ACCEPTED",
            payload_size_bytes=storage_result.payload_size_bytes,
            is_inlined=storage_result.is_inlined,
        )
