"""Landis+Gyr Gridstream AMI Historical Backfill Stitch."""

from __future__ import annotations

from datetime import timedelta

from ip.sdk import StitchSpec, retry_policy
from ip.solutions.domains.energy.landis.fetch_landis_meter_readings import (
    fetch_landis_meter_readings,
)
from ip.solutions.domains.energy.landis.normalize_landis_meter_readings import (
    normalize_landis_meter_reading,
)

LANDIS_METER_READINGS_BACKFILL_STITCH = StitchSpec(
    id="energy.landis_meter_readings_backfill",
    name="Landis+Gyr Gridstream Meter Readings Backfill to Oracle MDM",
    trigger="command.hes.landis_backfill",
    connector=fetch_landis_meter_readings,
    transformer=normalize_landis_meter_reading,
    destination="mdm.meter_readings.inbound",
    retry=retry_policy(max_attempts=3, initial_backoff=timedelta(seconds=2)),
)

__all__ = ["LANDIS_METER_READINGS_BACKFILL_STITCH"]
