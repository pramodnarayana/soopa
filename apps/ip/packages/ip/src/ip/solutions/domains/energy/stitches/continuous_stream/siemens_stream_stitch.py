"""Siemens EnergyIP 24/7/365 Continuous Streaming Meter Reading Stitch."""

from __future__ import annotations

from datetime import timedelta

from ip.sdk import StitchSpec, retry_policy
from ip.solutions.domains.energy.siemens.fetch_siemens_meter_readings import (
    fetch_siemens_meter_readings,
)
from ip.solutions.domains.energy.siemens.normalize_siemens_meter_readings import (
    normalize_siemens_meter_reading,
)

SIEMENS_METER_READINGS_STREAM_STITCH = StitchSpec(
    id="energy.siemens_meter_readings_stream",
    name="Siemens EnergyIP 24/7 Continuous Streaming to Oracle MDM",
    trigger="stream.hes.siemens_readings",
    connector=fetch_siemens_meter_readings,
    transformer=normalize_siemens_meter_reading,
    destination="mdm.meter_readings.inbound",
    retry=retry_policy(max_attempts=5, initial_backoff=timedelta(milliseconds=500)),
)

__all__ = ["SIEMENS_METER_READINGS_STREAM_STITCH"]
