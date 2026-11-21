"""Landis+Gyr 24/7/365 Continuous Streaming Meter Reading Stitch."""

from __future__ import annotations

from datetime import timedelta

from ip.sdk import StitchSpec, retry_policy
from ip.solutions.domains.energy.landis.fetch_landis_meter_readings import (
    fetch_landis_meter_readings,
)
from ip.solutions.domains.energy.landis.normalize_landis_meter_readings import (
    normalize_landis_meter_reading,
)

LANDIS_METER_READINGS_STREAM_STITCH = StitchSpec(
    id="energy.landis_meter_readings_stream",
    name="Landis+Gyr Gridstream 24/7 Continuous Streaming to Oracle MDM",
    trigger="stream.hes.landis_readings",
    connector=fetch_landis_meter_readings,
    transformer=normalize_landis_meter_reading,
    destination="mdm.meter_readings.inbound",
    retry=retry_policy(max_attempts=5, initial_backoff=timedelta(milliseconds=500)),
)

__all__ = ["LANDIS_METER_READINGS_STREAM_STITCH"]
