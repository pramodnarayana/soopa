"""Landis+Gyr Outage Ingestion Stitch."""

from __future__ import annotations

from datetime import timedelta

from ip.sdk import StitchSpec, retry_policy
from ip.solutions.domains.energy.landis.fetch_landis_outages import (
    fetch_landis_outages,
)
from ip.solutions.domains.energy.landis.normalize_landis_outages import (
    normalize_landis_outage,
)

LANDIS_OUTAGES_STITCH = StitchSpec(
    id="energy.landis_outages_ingestion",
    name="Landis+Gyr Power Outage Ingestion Pipeline",
    trigger="command.hes.landis_outages",
    connector=fetch_landis_outages,
    transformer=normalize_landis_outage,
    destination="mdm.outages.inbound",
    retry=retry_policy(max_attempts=3, initial_backoff=timedelta(seconds=2)),
)

__all__ = ["LANDIS_OUTAGES_STITCH"]
