"""Itron OpenWay AMI Historical Backfill Stitch."""

from __future__ import annotations

from datetime import timedelta

from ip.sdk import StitchSpec, retry_policy
from ip.solutions.domains.energy.itron.fetch_itron_meter_readings import (
    fetch_itron_meter_readings,
)
from ip.solutions.domains.energy.itron.normalize_itron_meter_readings import (
    normalize_itron_meter_reading,
)

ITRON_METER_READINGS_BACKFILL_STITCH = StitchSpec(
    id="energy.itron_meter_readings_backfill",
    name="Itron OpenWay Meter Readings Backfill to Oracle MDM",
    trigger="command.hes.itron_backfill",
    connector=fetch_itron_meter_readings,
    transformer=normalize_itron_meter_reading,
    destination="mdm.meter_readings.inbound",
    retry=retry_policy(max_attempts=3, initial_backoff=timedelta(seconds=2)),
)

__all__ = ["ITRON_METER_READINGS_BACKFILL_STITCH"]
