"""Pure Functional Stitch for Multi-HES Meter Reading Backfill and Extraction.

Orchestrates and stitches together decoupled, vendor-specific HES fetcher and normalizer functions:
- Itron OpenWay (`fetch_itron_meter_readings`, `normalize_itron_meter_reading`)
- Siemens EnergyIP (`fetch_siemens_meter_readings`, `normalize_siemens_meter_reading`)
- Landis+Gyr Gridstream (`fetch_landis_meter_readings`, `normalize_landis_meter_reading`)

Adheres strictly to Enterprise Architecture standards:
- 100% Pure Python, zero framework decorators, zero global state.
- Zero Adapter-to-Adapter coupling: Each vendor package is completely isolated.
- Inversion of Control: Network I/O is performed via injected StitchContext ports.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import TypeAlias

import structlog
from seedwork.domain.types import JsonDict

from ip.sdk import (
    RequestSpec,
    StitchContext,
    StitchSpec,
    parse_iso_datetime,
    retry_policy,
)
from ip.solutions.domains.energy.canonical import CanonicalMeterReadingDTO
from ip.solutions.domains.energy.commands import MeterReadingExtractCommand
from ip.solutions.domains.energy.itron.fetch_itron_meter_readings import (
    fetch_itron_meter_readings,
)
from ip.solutions.domains.energy.itron.normalize_itron_meter_readings import (
    normalize_itron_meter_reading,
)
from ip.solutions.domains.energy.landis.fetch_landis_meter_readings import (
    fetch_landis_meter_readings,
)
from ip.solutions.domains.energy.landis.normalize_landis_meter_readings import (
    normalize_landis_meter_reading,
)
from ip.solutions.domains.energy.siemens.fetch_siemens_meter_readings import (
    fetch_siemens_meter_readings,
)
from ip.solutions.domains.energy.siemens.normalize_siemens_meter_readings import (
    normalize_siemens_meter_reading,
)

logger = structlog.get_logger()

# Type aliases for pure decoupled functions
HesFetcherFn: TypeAlias = Callable[[MeterReadingExtractCommand], RequestSpec]
HesNormalizerFn: TypeAlias = Callable[[JsonDict], CanonicalMeterReadingDTO]


@dataclass(frozen=True)
class HesBackfillCommand:
    """Co-located CQRS command requesting interval meter readings backfill across HES targets."""

    tenant_id: str
    correlation_id: str
    start_time: str
    end_time: str
    meter_serials: tuple[str, ...] = ()
    hes_targets: tuple[str, ...] = ("conn_itron_hes", "conn_siemens_hes", "conn_landis_hes")
    reading_type: str = "15_MIN_INTERVAL"


@dataclass(frozen=True)
class HesDispatchedJob:
    """Dispatched asynchronous extraction job descriptor."""

    hes_target: str
    slice_start: str
    slice_end: str
    job_id: str
    status: str
    request_path: str
    request_method: str


@dataclass(frozen=True)
class HesBackfillResult:
    """Summary of all time-sliced extraction jobs dispatched across HES targets."""

    correlation_id: str
    total_slices: int
    dispatched_jobs: tuple[HesDispatchedJob, ...]


def resolve_hes_fetcher(hes_target: str) -> HesFetcherFn:
    """Resolves the pure vendor-specific fetcher function for a given HES target.

    Pure function with zero side effects.
    """
    normalized = hes_target.lower()
    if "itron" in normalized:
        return fetch_itron_meter_readings
    if "siemens" in normalized or "energyip" in normalized:
        return fetch_siemens_meter_readings
    if "landis" in normalized or "gridstream" in normalized:
        return fetch_landis_meter_readings

    raise ValueError(
        f"Unsupported HES target connection: '{hes_target}'. Expected itron, siemens, or landis."
    )


def resolve_hes_normalizer(hes_target: str) -> HesNormalizerFn:
    """Resolves the pure vendor-specific normalizer function for a given HES target."""
    normalized = hes_target.lower()
    if "itron" in normalized:
        return normalize_itron_meter_reading
    if "siemens" in normalized or "energyip" in normalized:
        return normalize_siemens_meter_reading
    if "landis" in normalized or "gridstream" in normalized:
        return normalize_landis_meter_reading

    raise ValueError(
        f"Unsupported HES normalizer target: '{hes_target}'. Expected itron, siemens, or landis."
    )


async def execute_multi_hes_backfill(
    ctx: StitchContext,
    cmd: HesBackfillCommand,
) -> HesBackfillResult:
    """Stitches together vendor-specific HES extractions into atomic daily slices.

    Pure function taking typed StitchContext with zero decorators or global state.
    """
    bound_logger = logger.bind(
        tenant_id=ctx.tenant_id,
        trace_id=ctx.trace_id,
        correlation_id=cmd.correlation_id,
    )
    bound_logger.info(
        "multi_hes_backfill_started",
        hes_targets=cmd.hes_targets,
        start_time=cmd.start_time,
        end_time=cmd.end_time,
    )

    start_dt = parse_iso_datetime(cmd.start_time)
    end_dt = parse_iso_datetime(cmd.end_time)

    # 1. Partition date range into atomic daily time slices via injected slicer port
    time_slices = ctx.slicer.slice_daily(start_dt, end_dt)
    dispatched: list[HesDispatchedJob] = []

    # 2. Iterate each HES target and stitch the vendor-specific fetcher
    for hes_conn in cmd.hes_targets:
        fetcher = resolve_hes_fetcher(hes_conn)
        for slice_item in time_slices:
            # Build pure command for this atomic slice
            slice_cmd = MeterReadingExtractCommand(
                start_time=slice_item.start_iso,
                end_time=slice_item.end_iso,
                meter_serials=cmd.meter_serials,
                reading_type=cmd.reading_type,
            )

            # Generate the decoupled vendor RequestSpec via pure domain function
            req_spec = fetcher(slice_cmd)

            # Dispatch via injected HTTP port
            if hasattr(ctx.http, "dispatch_spec"):
                resp = await ctx.http.dispatch_spec(connection_id=hes_conn, spec=req_spec)
            else:
                dispatch_payload: JsonDict
                if isinstance(req_spec.body, dict):
                    dispatch_payload = req_spec.body
                elif req_spec.body is not None:
                    dispatch_payload = {"raw_body": str(req_spec.body)}
                else:
                    dispatch_payload = {}
                resp = await ctx.http.dispatch(
                    connection_id=hes_conn,
                    endpoint=req_spec.path,
                    payload=dispatch_payload,
                    method=req_spec.method,
                    headers=req_spec.headers,
                )

            job_id = str(resp.get("job_id", f"job_{hes_conn}_{slice_item.start_iso}"))
            dispatched.append(
                HesDispatchedJob(
                    hes_target=hes_conn,
                    slice_start=slice_item.start_iso,
                    slice_end=slice_item.end_iso,
                    job_id=job_id,
                    status=str(resp.get("status", "SUBMITTED")),
                    request_path=req_spec.path,
                    request_method=req_spec.method,
                )
            )

    bound_logger.info(
        "multi_hes_backfill_completed",
        total_jobs=len(dispatched),
        slices_per_target=len(time_slices),
    )

    return HesBackfillResult(
        correlation_id=cmd.correlation_id,
        total_slices=len(time_slices),
        dispatched_jobs=tuple(dispatched),
    )


MULTI_HES_BACKFILL_STITCH = StitchSpec(
    id="energy.multi_hes_meter_reading_backfill",
    trigger="command.hes.meter_reading_backfill",
    handler=execute_multi_hes_backfill,
    name="Multi-HES Meter Reading Backfill Stitch",
    description="Stitches together Itron, Siemens, and Landis+Gyr time-sliced interval extractions",
    retry=retry_policy(max_attempts=3, initial_backoff=timedelta(seconds=2)),
    step_timeout=timedelta(minutes=5),
    workflow_sla=timedelta(hours=1),
)

__all__ = [
    "MULTI_HES_BACKFILL_STITCH",
    "HesBackfillCommand",
    "HesBackfillResult",
    "HesDispatchedJob",
    "execute_multi_hes_backfill",
    "resolve_hes_fetcher",
    "resolve_hes_normalizer",
]
