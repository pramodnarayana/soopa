"""Energy domain L4 Stitch workflow definitions and stitch instances."""

from __future__ import annotations

from orchestration.domain.definition import WorkflowDefinition

from ip.engine.domain.stitch.stitch import Stitch
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
from ip.solutions.domains.energy.stitches.push_to_kafka import (
    PUSH_TO_KAFKA_STITCH,
    PushToKafkaCommand,
    PushToKafkaResult,
    push_to_kafka,
)
from ip.solutions.domains.energy.stitches.request_hes_data import (
    REQUEST_HES_DATA_STITCH,
    RequestHesDataCommand,
    RequestHesDataResult,
    request_hes_data,
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
    "PUSH_TO_KAFKA_STITCH",
    "REQUEST_HES_DATA_STITCH",
    "PushToKafkaCommand",
    "PushToKafkaResult",
    "RequestHesDataCommand",
    "RequestHesDataResult",
    "build_energy_stitch_definitions",
    "build_energy_stitches",
    "build_hes_historical_extraction_definition",
    "build_hes_historical_extraction_stitch",
    "build_meter_reading_erp_sync_definition",
    "build_meter_reading_erp_sync_stitch",
    "build_outage_restoration_definition",
    "push_to_kafka",
    "request_hes_data",
]
