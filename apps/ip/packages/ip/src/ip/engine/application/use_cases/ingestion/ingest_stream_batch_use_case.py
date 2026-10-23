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
from ip.engine.ports.outbound.subscribe_transport_port import RawMessageBatchDTO
from ip.engine.ports.outbound.tiered_storage_port import TieredStoragePort
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

        try:
            async with self._uow:
                for msg in command.batch.messages:
                    # 1. Deduplication check: drop duplicate network retries
                    if msg.message_id:
                        existing = await self._uow.inbound_records.get_by_external_event_id(
                            tenant_id=command.tenant_id,
                            connection_id=command.connection_id,
                            external_event_id=msg.message_id,
                        )
                        if existing is not None:
                            logger.info(
                                "stream_message_duplicate_skipped",
                                tenant_id=command.tenant_id,
                                connection_id=command.connection_id,
                                stream_name=command.stream_name,
                                external_event_id=msg.message_id,
                                existing_record_id=existing.id,
                                trace_id=trace_id,
                            )
                            duplicates_skipped += 1
                            continue

                    # 2. Decode payload
                    decode_res = self._decoder.decode(
                        content_type=msg.content_type,
                        raw_body=msg.raw_payload,
                    )
                    decoded_payload: JsonValue | None = (
                        decode_res.value
                        if decode_res.is_ok and isinstance(decode_res.value, (dict, list))
                        else None
                    )

                    # 3. Tiered storage (> 64KB offloaded to S3)
                    storage_result = await self._tiered_storage.store(
                        tenant_id=command.tenant_id,
                        trace_id=trace_id,
                        payload_bytes=msg.raw_payload,
                        parsed_payload=decoded_payload,
                    )

                    # 4. Construct and save InboundRecord
                    headers_dict: dict[str, JsonValue] = {
                        str(k): str(v) for k, v in msg.headers.items()
                    }
                    if msg.partition_id:
                        headers_dict["x-stream-partition"] = str(msg.partition_id)
                    if msg.broker_offset:
                        headers_dict["x-stream-offset"] = str(msg.broker_offset)

                    record = InboundRecord.create(
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
                    await self._uow.inbound_records.save(record)
                    record_ids.append(record.id)

                # 5. Atomic commit to L1 Data Plane
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
            logger.error(
                "stream_batch_ingestion_data_rejected",
                tenant_id=command.tenant_id,
                connection_id=command.connection_id,
                stream_name=command.stream_name,
                error=str(exc),
                trace_id=trace_id,
            )
            return IngestStreamBatchResultDTO(
                verdict=AckVerdict.REJECT,
                records_ingested=0,
                duplicates_skipped=duplicates_skipped,
                trace_id=trace_id,
                error_message=str(exc),
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
