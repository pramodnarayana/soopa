"""HES 1 File Backfill Stitch: Asynchronous temporal slicing, S3 Bronze streaming, and pipeline execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from seedwork.domain.types import JsonDict

from ip.engine.domain.normalization.dtos import TransformationContext
from ip.sdk import (
    RequestSpec,
    StitchContext,
    StitchSpec,
    retry_policy,
)
from ip.solutions.domains.energy.canonical import CanonicalMeterReadingDTO
from ip.solutions.domains.energy.commands import MeterReadingExtractCommand
from ip.solutions.domains.energy.landis.fetch_landis_meter_readings import (
    fetch_landis_meter_readings,
)
from ip.solutions.domains.energy.landis.normalize_landis_meter_readings import (
    normalize_landis_meter_reading,
)


def execute_hes1_file_backfill_request(
    command_payload: JsonDict,
    ctx: StitchContext,
) -> RequestSpec:
    """Builds the file extract request for HES 1 historical batch export."""
    raw_start = str(command_payload.get("start_time") or datetime.now(UTC).isoformat())
    raw_end = str(
        command_payload.get("end_time") or (datetime.now(UTC) + timedelta(days=1)).isoformat()
    )

    serials_raw = (
        command_payload.get("meter_serials") or command_payload.get("meter_serial_numbers") or ()
    )
    serials: tuple[str, ...] = (
        tuple(str(s) for s in serials_raw) if isinstance(serials_raw, (list, tuple)) else ()
    )

    cmd = MeterReadingExtractCommand(
        start_time=raw_start,
        end_time=raw_end,
        meter_serials=serials,
    )
    return fetch_landis_meter_readings(cmd)


def transform_hes1_file_reading(
    raw_record: JsonDict,
    ctx: TransformationContext,
) -> CanonicalMeterReadingDTO | None:
    """Normalizes raw file records to canonical CIM format."""
    return normalize_landis_meter_reading(raw_record, ctx)


HES1_FILE_BACKFILL_STITCH = StitchSpec(
    id="energy.hes1_file_backfill",
    name="HES 1 Asynchronous File Pull Backfill to Oracle MDM",
    trigger="command.hes1.file_backfill",
    connector=execute_hes1_file_backfill_request,
    transformer=transform_hes1_file_reading,
    destination="mdm.meter_readings.inbound",
    retry=retry_policy(max_attempts=3, initial_backoff=timedelta(seconds=5)),
)

__all__ = [
    "HES1_FILE_BACKFILL_STITCH",
    "execute_hes1_file_backfill_request",
    "transform_hes1_file_reading",
]
