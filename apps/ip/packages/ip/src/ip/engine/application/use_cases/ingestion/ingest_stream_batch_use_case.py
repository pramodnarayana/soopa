"""Use case implementing the Strict At-Least-Once Handshake for streaming subscriptions (Kafka, RabbitMQ, MQTT, SQS)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from seedwork.domain.types import JsonValue
from seedwork.id_registry import DomainIdPrefix
from seedwork.utils import generate_id

from ip.engine.domain.enums import AckVerdict, IngestionMode
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.ports.outbound.inbound_payload_decoder_port import InboundPayloadDecoderPort
from ip.engine.ports.outbound.subscribe_transport_port import (
    RawMessageBatchDTO,
    RawMessageDTO,
)
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class IngestStreamBatchCommand:
    """Command payload representing a batch of raw messages consumed from a streaming broker."""

    tenant_id: str
    connection_id: str
    app_id: str
    stream_name: str
    batch: RawMessageBatchDTO
    trace_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class IngestStreamBatchResultDTO:
    """Outcome of processing a streaming message batch through L1 Data Plane."""

    verdict: AckVerdict
    records_ingested: int
    duplicates_skipped: int
    trace_id: str
    record_ids: Sequence[str] = ()
    error_message: str | None = None


class IngestStreamBatchUseCase:
    """Atomic ingestion coordinator enforcing the Strict At-Least-Once Handshake.

    Sequence:
    1. Deliver message batch from broker.
    2. Decode payload (JSON / Avro / XML / Protobuf / raw).
    3. BEGIN TRANSACTION in L1 Data Plane.
    4. Deduplicate on (connection_id, external_event_id).
    5. INSERT into inbound_records (with tiered storage for >64KB).
    6. COMMIT TRANSACTION in L1 Data Plane.
    7. AFTER COMMIT: Return AckVerdict.ACK (allowing transport to commit offset / send ACK).
       On any DB or storage failure, returns AckVerdict.NACK (broker redelivers).
    """

    def __init__(
        self,
        uow: IpDataPlaneUnitOfWorkPort,
        tiered_storage: TieredStoragePort,
        decoder: InboundPayloadDecoderPort,
    ) -> None:
        self._uow = uow
        self._tiered_storage = tiered_storage
        self._decoder = decoder

    async def execute(self, command: IngestStreamBatchCommand) -> IngestStreamBatchResultDTO:
        trace_id = command.trace_id or generate_id(DomainIdPrefix.IP_TRACE.value)
        record_ids: list[str] = []
        duplicates_skipped = 0
        seen_batch_ids: set[str] = set()

        try:
            async with self._uow:
                for msg in command.batch.messages:
                    if await self._is_duplicate_message(
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        stream_name=command.stream_name,
                        message_id=msg.message_id,
                        trace_id=trace_id,
                        seen_batch_ids=seen_batch_ids,
                    ):
                        duplicates_skipped += 1
                        continue

                    record_id = await self._ingest_normal_message(
                        command=command,
                        msg=msg,
                        trace_id=trace_id,
                    )
                    record_ids.append(record_id)

                await self._uow.commit()

            logger.info(
                "stream_batch_ingested_successfully",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
                records_ingested=len(record_ids),
                duplicates_skipped=duplicates_skipped,
                trace_id=trace_id,
            )
            return IngestStreamBatchResultDTO(
                verdict=AckVerdict.ACK,
                records_ingested=len(record_ids),
                duplicates_skipped=duplicates_skipped,
                record_ids=record_ids,
                trace_id=trace_id,
            )

        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return await self._handle_batch_rejection(
                command=command,
                trace_id=trace_id,
                exc=exc,
            )
        except Exception as exc:
            logger.exception(
                "stream_batch_ingestion_transaction_failed",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
                error=str(exc),
                trace_id=trace_id,
            )
            return IngestStreamBatchResultDTO(
                verdict=AckVerdict.NACK,
                records_ingested=0,
                duplicates_skipped=duplicates_skipped,
                trace_id=trace_id,
                error_message=str(exc),
            )

    async def _handle_batch_rejection(
        self,
        command: IngestStreamBatchCommand,
        trace_id: str,
        exc: Exception,
    ) -> IngestStreamBatchResultDTO:
        logger.error(
            "stream_batch_ingestion_data_rejected",
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            stream_name=command.stream_name,
            error=str(exc),
            trace_id=trace_id,
        )
        duplicates_skipped = 0
        record_ids: list[str] = []
        seen_batch_ids: set[str] = set()

        try:
            async with self._uow:
                for msg in command.batch.messages:
                    if await self._is_duplicate_message(
                        tenant_id=command.tenant_id,
                        connection_id=command.connection_id,
                        stream_name=command.stream_name,
                        message_id=msg.message_id,
                        trace_id=trace_id,
                        seen_batch_ids=seen_batch_ids,
                    ):
                        duplicates_skipped += 1
                        continue

                    try:
                        record_id = await self._ingest_normal_message(
                            command=command,
                            msg=msg,
                            trace_id=trace_id,
                        )
                        record_ids.append(record_id)
                    except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as msg_exc:
                        await self._persist_rejected_record(
                            command=command,
                            msg=msg,
                            trace_id=trace_id,
                            exc=msg_exc,
                        )

                await self._uow.commit()
        except Exception as persist_exc:
            logger.exception(
                "stream_batch_rejection_record_failed",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                error=str(persist_exc),
                trace_id=trace_id,
            )
            return IngestStreamBatchResultDTO(
                verdict=AckVerdict.NACK,
                records_ingested=0,
                duplicates_skipped=duplicates_skipped,
                trace_id=trace_id,
                error_message=str(exc),
            )

        return IngestStreamBatchResultDTO(
            verdict=AckVerdict.REJECT,
            records_ingested=len(record_ids),
            duplicates_skipped=duplicates_skipped,
            record_ids=record_ids,
            trace_id=trace_id,
            error_message=str(exc),
        )

    async def _is_duplicate_message(
        self,
        *,
        tenant_id: str,
        connection_id: str,
        stream_name: str,
        message_id: str | None,
        trace_id: str,
        seen_batch_ids: set[str],
    ) -> bool:
        if not message_id:
            return False
        if message_id in seen_batch_ids:
            logger.info(
                "stream_message_duplicate_skipped",
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
                external_event_id=message_id,
                trace_id=trace_id,
            )
            return True
        existing = await self._uow.inbound_records.get_by_external_event_id(
            tenant_id=tenant_id,
            connection_id=connection_id,
            external_event_id=message_id,
        )
        if existing is not None:
            seen_batch_ids.add(message_id)
            logger.info(
                "stream_message_duplicate_skipped",
                tenant_id=tenant_id,
                connection_id=connection_id,
                stream_name=stream_name,
                external_event_id=message_id,
                existing_record_id=existing.id,
                trace_id=trace_id,
            )
            return True
        seen_batch_ids.add(message_id)
        return False

    def _build_inbound_headers(self, msg: RawMessageDTO) -> dict[str, JsonValue]:
        headers_dict: dict[str, JsonValue] = {str(k): str(v) for k, v in msg.headers.items()}
        if msg.partition_id:
            headers_dict["x-stream-partition"] = str(msg.partition_id)
        if msg.broker_offset:
            headers_dict["x-stream-offset"] = str(msg.broker_offset)
        return headers_dict

    def _build_normal_record(
        self,
        *,
        command: IngestStreamBatchCommand,
        msg: RawMessageDTO,
        storage_result: TieredStorageResultDTO,
        trace_id: str,
    ) -> InboundRecord:
        headers_dict = self._build_inbound_headers(msg)
        return InboundRecord.create(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            app_id=command.app_id,
            stream_name=command.stream_name,
            payload_bytes=msg.raw_payload,
            is_inlined=storage_result.is_inlined,
            trace_id=trace_id,
            correlation_id=command.correlation_id,
            ingestion_mode=IngestionMode.STREAM_SUBSCRIBE,
            external_event_id=msg.message_id,
            request_headers=headers_dict,
            request_body=storage_result.raw_payload,
            request_s3_key=storage_result.s3_key,
            response_status_code=200,
        )

    async def _ingest_normal_message(
        self,
        *,
        command: IngestStreamBatchCommand,
        msg: RawMessageDTO,
        trace_id: str,
    ) -> str:
        decode_res = self._decoder.decode(
            content_type=msg.content_type,
            raw_body=msg.raw_payload,
        )
        decoded_payload: JsonValue | None = (
            decode_res.value
            if decode_res.is_ok and isinstance(decode_res.value, (dict, list))
            else None
        )
        storage_result = await self._tiered_storage.store(
            tenant_id=command.tenant_id,
            trace_id=trace_id,
            payload_bytes=msg.raw_payload,
            parsed_payload=decoded_payload,
        )
        record = self._build_normal_record(
            command=command,
            msg=msg,
            storage_result=storage_result,
            trace_id=trace_id,
        )
        await self._uow.inbound_records.save(record)
        return record.id

    async def _persist_rejected_record(
        self,
        *,
        command: IngestStreamBatchCommand,
        msg: RawMessageDTO,
        trace_id: str,
        exc: Exception,
    ) -> None:
        storage_result = await self._tiered_storage.store(
            tenant_id=command.tenant_id,
            trace_id=trace_id,
            payload_bytes=msg.raw_payload,
            parsed_payload=None,
        )
        headers_dict = self._build_inbound_headers(msg)
        headers_dict["x-rejection-reason"] = str(exc)

        body_data = dict(storage_result.raw_payload or {})
        body_data["error"] = str(exc)
        body_data["status"] = "REJECTED"

        rejected_record = InboundRecord.create(
            tenant_id=command.tenant_id,
            connection_id=command.connection_id,
            app_id=command.app_id,
            stream_name=command.stream_name,
            payload_bytes=msg.raw_payload,
            is_inlined=storage_result.is_inlined,
            trace_id=trace_id,
            correlation_id=command.correlation_id,
            ingestion_mode=IngestionMode.STREAM_SUBSCRIBE,
            external_event_id=msg.message_id,
            request_headers=headers_dict,
            request_body=body_data if storage_result.is_inlined else None,
            request_s3_key=storage_result.s3_key if not storage_result.is_inlined else None,
            response_status_code=422,
        )
        rejected_record.clear_domain_events()
        await self._uow.inbound_records.save(rejected_record)
