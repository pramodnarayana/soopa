"""HES 2 Kafka Backfill Stitch: Bounded stream consumer drain, micro-batching, and Oracle MDM Kafka delivery."""

from __future__ import annotations

from datetime import timedelta

from seedwork.domain.types import JsonDict

from ip.engine.domain.normalization.dtos import TransformationContext
from ip.sdk import (
    RequestSpec,
    StitchContext,
    StitchSpec,
    retry_policy,
)
from ip.solutions.domains.energy.canonical import CanonicalMeterReadingDTO
from ip.solutions.domains.energy.siemens.normalize_siemens_meter_readings import (
    normalize_siemens_meter_reading,
)


def drain_hes2_kafka_stream(
    command_payload: JsonDict,
    ctx: StitchContext,
) -> RequestSpec:
    """Configures the consumer subscription for HES 2 replay drain."""
    topic = str(command_payload.get("source_topic") or "hes2.replay.intervals")
    return RequestSpec(
        method="KAFKA_CONSUME",
        path=f"kafka://{topic}",
        headers={"consumer_group": f"ip-hes2-drain-{ctx.tenant_id}"},
    )


def transform_hes2_kafka_reading(
    raw_record: JsonDict,
    ctx: TransformationContext,
) -> CanonicalMeterReadingDTO | None:
    """Normalizes HES 2 stream records to canonical CIM format."""
    return normalize_siemens_meter_reading(raw_record, ctx)


HES2_KAFKA_BACKFILL_STITCH = StitchSpec(
    id="energy.hes2_kafka_backfill",
    name="HES 2 Bounded Kafka Replay Drain to Oracle MDM",
    trigger="command.hes2.kafka_drain",
    connector=drain_hes2_kafka_stream,
    transformer=transform_hes2_kafka_reading,
    destination="mdm.meter_readings.inbound",
    retry=retry_policy(max_attempts=3, initial_backoff=timedelta(seconds=2)),
)

__all__ = [
    "HES2_KAFKA_BACKFILL_STITCH",
    "drain_hes2_kafka_stream",
    "transform_hes2_kafka_reading",
]
