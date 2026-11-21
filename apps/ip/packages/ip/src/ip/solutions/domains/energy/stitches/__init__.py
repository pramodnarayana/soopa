"""Energy domain L4 Stitch workflow definitions and stitch instances."""

from __future__ import annotations

from orchestration.domain.definition import WorkflowDefinition

from ip.engine.domain.stitch.stitch import Stitch
from ip.solutions.domains.energy.stitches.backfill import (
    ITRON_METER_READINGS_BACKFILL_STITCH,
    LANDIS_METER_READINGS_BACKFILL_STITCH,
    MULTI_HES_BACKFILL_STITCH,
    SIEMENS_METER_READINGS_BACKFILL_STITCH,
    HesBackfillCommand,
    HesBackfillResult,
    HesDispatchedJob,
    execute_multi_hes_backfill,
    resolve_hes_fetcher,
    resolve_hes_normalizer,
)
from ip.solutions.domains.energy.stitches.continuous_stream import (
    ITRON_METER_READINGS_STREAM_STITCH,
    LANDIS_METER_READINGS_STREAM_STITCH,
    SIEMENS_METER_READINGS_STREAM_STITCH,
)
from ip.solutions.domains.energy.stitches.hes_historical_extraction import (
    build_hes_historical_extraction_definition,
    build_hes_historical_extraction_stitch,
)
from ip.solutions.domains.energy.stitches.meter_reading_erp_sync import (
    build_meter_reading_erp_sync_definition,
    build_meter_reading_erp_sync_stitch,
)
from ip.solutions.domains.energy.stitches.outage_restoration import (
    build_outage_restoration_definition,
)
from ip.solutions.domains.energy.stitches.outages import (
    LANDIS_OUTAGES_STITCH,
)
from ip.solutions.domains.energy.stitches.push_to_kafka import (
    PUSH_TO_KAFKA_STITCH,
    PushToKafkaCommand,
    PushToKafkaResult,
    push_to_kafka,
)


def build_energy_stitch_definitions() -> tuple[WorkflowDefinition, ...]:
    """Return all built-in WorkflowDefinitions owned by the Energy bounded context."""
    return (
        build_outage_restoration_definition(),
        build_meter_reading_erp_sync_definition(),
        build_hes_historical_extraction_definition(),
    )


def build_energy_stitches() -> tuple[Stitch, ...]:
    """Return all built-in Stitch instances owned by the Energy bounded context."""
    return (
        build_meter_reading_erp_sync_stitch(),
        build_hes_historical_extraction_stitch(),
    )


__all__ = [
    "ITRON_METER_READINGS_BACKFILL_STITCH",
    "ITRON_METER_READINGS_STREAM_STITCH",
    "LANDIS_METER_READINGS_BACKFILL_STITCH",
    "LANDIS_METER_READINGS_STREAM_STITCH",
    "LANDIS_OUTAGES_STITCH",
    "MULTI_HES_BACKFILL_STITCH",
    "PUSH_TO_KAFKA_STITCH",
    "SIEMENS_METER_READINGS_BACKFILL_STITCH",
    "SIEMENS_METER_READINGS_STREAM_STITCH",
    "HesBackfillCommand",
    "HesBackfillResult",
    "HesDispatchedJob",
    "PushToKafkaCommand",
    "PushToKafkaResult",
    "build_energy_stitch_definitions",
    "build_energy_stitches",
    "build_hes_historical_extraction_definition",
    "build_hes_historical_extraction_stitch",
    "build_meter_reading_erp_sync_definition",
    "build_meter_reading_erp_sync_stitch",
    "build_outage_restoration_definition",
    "execute_multi_hes_backfill",
    "push_to_kafka",
    "resolve_hes_fetcher",
    "resolve_hes_normalizer",
]
