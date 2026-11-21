"""Itron OpenWay 24/7/365 Continuous Streaming Meter Reading Stitch."""

from __future__ import annotations

from datetime import timedelta

from ip.sdk import StitchSpec, retry_policy
from ip.solutions.domains.energy.itron.fetch_itron_meter_readings import (
    fetch_itron_meter_readings,
)
from ip.solutions.domains.energy.itron.normalize_itron_meter_readings import (
    normalize_itron_meter_reading,
)

ITRON_METER_READINGS_STREAM_STITCH = StitchSpec(
    id="energy.itron_meter_readings_stream",
    name="Itron OpenWay 24/7 Continuous Streaming to Oracle MDM",
    trigger="stream.hes.itron_readings",
    connector=fetch_itron_meter_readings,
    transformer=normalize_itron_meter_reading,
    destination="mdm.meter_readings.inbound",
    retry=retry_policy(max_attempts=5, initial_backoff=timedelta(milliseconds=500)),
)

__all__ = ["ITRON_METER_READINGS_STREAM_STITCH"]
