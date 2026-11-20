"""Functional Stitch for publishing canonical meter readings to the destination Kafka queue.

Adheres strictly to the Single Responsibility Principle (SRP):
- Owns ONLY delivery of canonical CIM meter readings to the destination Kafka topic.
- Does NOT know anything about HES extraction or time slicing.
- Resolves destination credentials dynamically via logical connection alias configured in the UI.
- 100% pure function, zero decorators, zero framework inheritance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import structlog
from seedwork.domain.types import JsonDict

from ip.sdk import (
    StitchContext,
    StitchSpec,
    retry_policy,
)
from ip.solutions.domains.energy.canonical import CanonicalMeterReadingDTO

logger = structlog.get_logger()


@dataclass(frozen=True)
class PushToKafkaCommand:
    """Co-located CQRS command for publishing canonical readings to Kafka."""

    tenant_id: str
    topic: str
    records: tuple[CanonicalMeterReadingDTO, ...]
    connection_id: str = "conn_oracle_mdm_kafka"


@dataclass(frozen=True)
class PushToKafkaResult:
    """Summary of records delivered to Kafka."""

    topic: str
    connection_id: str
    published_count: int
    status: str


async def push_to_kafka(
    ctx: StitchContext,
    cmd: PushToKafkaCommand,
) -> PushToKafkaResult:
    """Publishes canonical CIM meter readings to the destination Kafka queue.

    Connection resolution:
    - The connection alias (`cmd.connection_id`, configured via UI) is passed to `ctx.kafka.publish`.
    - The platform outbound adapter resolves the cluster bootstrap servers, SASL credentials,
      and mTLS certificates from secure storage (AWS KMS / Vault) in memory.
    - Zero secrets or network endpoints are exposed or hardcoded in solution code.
    """
    bound_logger = logger.bind(
        tenant_id=ctx.tenant_id,
        trace_id=ctx.trace_id,
        connection_id=cmd.connection_id,
        topic=cmd.topic,
    )
    bound_logger.info(
        "push_to_kafka_started",
        record_count=len(cmd.records),
    )

    published = 0
    for reading in cmd.records:
        payload: JsonDict = {
            "id": reading.id,
            "meter_serial_number": reading.meter_serial_number,
            "reading_timestamp": reading.reading_timestamp.isoformat(),
            "interval_minutes": reading.interval_minutes,
            "kwh_delivered": reading.kwh_delivered,
            "kwh_received": reading.kwh_received,
            "quality_flag": reading.quality_flag,
            "recorded_at": reading.recorded_at.isoformat(),
            "tenant_id": reading.tenant_id,
            "trace_id": reading.trace_id,
        }

        # Deliver to partition using meter_serial_number as partition key for FIFO ordering
        await ctx.kafka.publish(
            connection_id=cmd.connection_id,
            topic=cmd.topic,
            partition_key=reading.meter_serial_number,
            payload=payload,
            headers={
                "x-tenant-id": ctx.tenant_id,
                "x-trace-id": ctx.trace_id,
                "x-source-app": "soopa-ip-stitch",
            },
        )
        published += 1

    bound_logger.info(
        "push_to_kafka_completed",
        published_count=published,
    )

    return PushToKafkaResult(
        topic=cmd.topic,
        connection_id=cmd.connection_id,
        published_count=published,
        status="DELIVERED",
    )


PUSH_TO_KAFKA_STITCH = StitchSpec(
    id="energy.push_to_kafka",
    trigger="canonical.meter_readings.normalized",
    handler=push_to_kafka,
    name="Push Readings To Kafka",
    description="Publishes canonical meter readings to Oracle MDM Kafka destination queue",
    retry=retry_policy(max_attempts=5, initial_backoff=timedelta(seconds=1)),
    step_timeout=timedelta(minutes=2),
)

__all__ = [
    "PUSH_TO_KAFKA_STITCH",
    "PushToKafkaCommand",
    "PushToKafkaResult",
    "push_to_kafka",
]
