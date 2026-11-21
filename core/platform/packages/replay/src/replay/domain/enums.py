"""Universal platform replay enums (core/platform/packages/replay)."""

from __future__ import annotations

from enum import StrEnum


class ReplayStage(StrEnum):
    """Universal pipeline stages available for re-execution across any domain."""

    STAGE_1_RAW_INGRESS = "STAGE_1_RAW_INGRESS"  # Raw pristine vendor/source payload (.raw.zst)
    STAGE_2_STAGED_REPLICA = "STAGE_2_STAGED_REPLICA"  # Deduplicated replica storage
    STAGE_3_CANONICAL_MODEL = (
        "STAGE_3_CANONICAL_MODEL"  # Canonical normalized domain model (Silver CIM/Parquet)
    )
    STAGE_4_WIRE_EGRESS = "STAGE_4_WIRE_EGRESS"  # Final destination wire delivery (Kafka/HTTP)


class ReplayTargetType(StrEnum):
    """Type of boundary or entity being replayed."""

    BATCH = "BATCH"
    RECORD = "RECORD"
    STREAM = "STREAM"


class ReplayStatus(StrEnum):
    """Execution status of a replay operation."""

    INITIATED = "INITIATED"
    IN_FLIGHT = "IN_FLIGHT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
