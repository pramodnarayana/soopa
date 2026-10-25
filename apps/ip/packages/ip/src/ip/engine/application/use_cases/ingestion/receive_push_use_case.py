"""Use case for verifying, deduplicating, and staging external push webhooks into L1."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import structlog
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from ip.engine.domain.enums import IngestionMode
from ip.engine.domain.events import FetchRecordRequestedEvent
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.ports.outbound.inbound_ack_port import InboundAckPort
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.inbound_verifier_port import InboundVerifierPort
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ReceivePushCommand:
    """Command payload for an incoming external push webhook."""

    tenant_id: str
    connection_id: str
    stream_name: str
    raw_payload: bytes
    headers: Mapping[str, JsonValue]
    secret: str | None = None
    app_id: str = ""
    external_event_id: str | None = None
    is_thin: bool = False
    thin_record_id: str | None = None
    ingestion_mode: IngestionMode | None = None
    sync_run_id: str | None = None
    generation_id: int | None = None
    response_status_code: int | None = None
    response_body: JsonDict | None = None
    duration_ms: int | None = None
    trace_id: str | None = None
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0


@dataclass(frozen=True)
class ReceivePushResultDTO:
    """HTTP acknowledgment response returned (<20ms) to the external caller."""

    status_code: int
    headers: Mapping[str, str]
    body: str | bytes | JsonDict
    trace_id: str
    record_id: str | None = None
    is_duplicate: bool = False
    is_verified: bool = True
    payload_size_bytes: int = 0
    is_inlined: bool = True


class ReceivePushUseCase:
    """Ingress Gateway coordinator for receiving, verifying, and persisting push notifications in L1."""

    def __init__(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        tiered_storage: TieredStoragePort,
        verifier: InboundVerifierPort,
        decoder: InboundPayloadDecoderPort,
        ack: InboundAckPort,
    ) -> None:
        self._uow = uow
        self._tiered_storage = tiered_storage
        self._verifier = verifier
        self._decoder = decoder
        self._ack = ack

    async def execute(self, command: ReceivePushCommand) -> ReceivePushResultDTO:
        trace_id = command.trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        str_headers: dict[str, str] = {str(k): str(v) for k, v in command.headers.items()}

        # 1. Verify webhook authenticity (Strategy pattern via InboundVerifierPort)
        verify_result = self._verifier.verify(
            headers=str_headers,
            raw_body=command.raw_payload,
            secret=command.secret or "",
        )
        if verify_result.is_err or not verify_result.value:
            logger.error(
                "inbound_push_verification_failed",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
                trace_id=trace_id,
            )
            return ReceivePushResultDTO(
                status_code=401,
                headers={"Content-Type": "application/json"},
                body={"error": "Unauthorized: Inbound verification failed"},
                trace_id=trace_id,
                is_verified=False,
            )

        # 2. Decode payload for storage and ACK formatting
        lowercased_headers = {k.lower(): v for k, v in str_headers.items()}
        content_type = lowercased_headers.get("content-type") or "application/json"
        decode_res = self._decoder.decode(
            content_type=content_type,
            raw_body=command.raw_payload,
        )
        decoded_payload: JsonValue = (
            decode_res.value
            if (decode_res.is_ok and decode_res.value is not None)
            else {"raw": command.raw_payload.decode("utf-8", errors="replace")}
        )

        # 3. Determine ingestion mode and evaluate tiered storage
        if command.ingestion_mode is not None:
            ingestion_mode = command.ingestion_mode
        else:
            ingestion_mode = IngestionMode.PUSH_THIN if command.is_thin else IngestionMode.PUSH_FULL

        parsed_payload: JsonValue | None = (
            decoded_payload if isinstance(decoded_payload, (dict, list)) else None
        )

        # 4. Check deduplication, store payload, and commit atomically inside DataPlaneUnitOfWork
        async with self._uow:
            if command.external_event_id:
                existing = await self._uow.inbound_records.get_by_external_event_id(
                    tenant_id=command.tenant_id,
                    connection_id=command.connection_id,
                    external_event_id=command.external_event_id,
                )
                if existing is not None:
                    logger.info(
                        "inbound_push_duplicate_ignored",
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        stream_name=command.stream_name,
                        external_event_id=command.external_event_id,
                        existing_record_id=existing.id,
                        trace_id=trace_id,
                    )
                    ack_response = self._ack.build_ack(
                        app_id=command.app_id,
                        payload={},
                        headers=str_headers,
                    )
                    return ReceivePushResultDTO(
                        status_code=ack_response.status_code,
                        headers=ack_response.headers,
                        body=ack_response.body,
                        record_id=existing.id,
                        trace_id=trace_id,
                        is_duplicate=True,
                        is_verified=True,
                        payload_size_bytes=existing.request_size_bytes,
                        is_inlined=existing.request_s3_key is None,
                    )

            storage_result = await self._tiered_storage.store(
                tenant_id=command.tenant_id,
                trace_id=trace_id,
                payload_bytes=command.raw_payload,
                parsed_payload=parsed_payload,
            )

            # 5. Create immutable InboundRecord aggregate root
            record = InboundRecord.create(
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                app_id=command.app_id,
                stream_name=command.stream_name,
                payload_bytes=command.raw_payload,
                is_inlined=storage_result.is_inlined,
                request_body=storage_result.raw_payload,
                request_s3_key=storage_result.s3_key,
                request_headers=dict(command.headers),
                response_status_code=command.response_status_code or 202,
                response_body=command.response_body,
                duration_ms=command.duration_ms,
                trace_id=trace_id,
                correlation_id=command.correlation_id,
                parent_trace_id=command.parent_trace_id,
                original_trace_id=command.original_trace_id,
                replay_count=command.replay_count,
                ingestion_mode=ingestion_mode,
                sync_run_id=command.sync_run_id,
                generation_id=command.generation_id,
                external_event_id=command.external_event_id,
            )

            # 6. For thin push, trigger async fetch
            if command.is_thin and command.thin_record_id:
                record.add_domain_event(
                    FetchRecordRequestedEvent(
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        stream=command.stream_name,
                        record_id=command.thin_record_id,
                        notice_inbound_record_id=record.id,
                        trace_id=trace_id,
                    )
                )

            await self._uow.inbound_records.save(record)
            await self._uow.commit()

        # 7. Generate provider-compliant ACK response
        ack_response = self._ack.build_ack(
            app_id=command.app_id,
            payload=decoded_payload,
            headers=str_headers,
        )

        logger.info(
            "inbound_push_received",
            record_id=record.id,
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream_name=command.stream_name,
            mode=ingestion_mode.value,
            trace_id=trace_id,
        )

        return ReceivePushResultDTO(
            status_code=ack_response.status_code,
            headers=ack_response.headers,
            body=ack_response.body,
            record_id=record.id,
            trace_id=trace_id,
            is_duplicate=False,
            is_verified=True,
            payload_size_bytes=storage_result.payload_size_bytes,
            is_inlined=storage_result.is_inlined,
        )
