"""Siemens EnergyIP AMI Historical Backfill Stitch."""

from __future__ import annotations

from datetime import timedelta

from ip.sdk import StitchSpec, retry_policy
from ip.solutions.domains.energy.siemens.fetch_siemens_meter_readings import (
    fetch_siemens_meter_readings,
)
from ip.solutions.domains.energy.siemens.normalize_siemens_meter_readings import (
    normalize_siemens_meter_reading,
)

SIEMENS_METER_READINGS_BACKFILL_STITCH = StitchSpec(
    id="energy.siemens_meter_readings_backfill",
    name="Siemens EnergyIP Meter Readings Backfill to Oracle MDM",
    trigger="command.hes.siemens_backfill",
    connector=fetch_siemens_meter_readings,
    transformer=normalize_siemens_meter_reading,
    destination="mdm.meter_readings.inbound",
    retry=retry_policy(max_attempts=3, initial_backoff=timedelta(seconds=2)),
)

__all__ = ["SIEMENS_METER_READINGS_BACKFILL_STITCH"]
