"""Functional Stitch for fanning out time-sliced data requests to 3 HES systems.

Adheres strictly to the Single Responsibility Principle (SRP):
- Owns ONLY the decomposition and dispatch of Oracle MDM extraction requests to HES systems.
- Does NOT perform normalization (handled purely by Highway L1->L3 normalizers).
- Does NOT push to Kafka (handled by PushToKafka stitch).
- 100% pure function, zero decorators, zero framework inheritance.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import structlog
from seedwork.domain.types import JsonDict

from ip.sdk import (
    StitchContext,
    StitchSpec,
    parse_iso_datetime,
    retry_policy,
)

logger = structlog.get_logger()


@dataclass(frozen=True)
class RequestHesDataCommand:
    """Co-located CQRS command requesting interval meter readings from HES."""

    tenant_id: str
    correlation_id: str
    start_time: str
    end_time: str
    meter_ids: tuple[str, ...] = ()
    hes_targets: tuple[str, ...] = ("conn_landis_hes", "conn_itron_hes", "conn_siemens_hes")


@dataclass(frozen=True)
class HesExtractJob:
    """Dispatched asynchronous extraction job descriptor."""

    hes_target: str
    slice_start: str
    slice_end: str
    job_id: str
    status: str


@dataclass(frozen=True)
class RequestHesDataResult:
    """Summary of all time-sliced jobs dispatched across HES targets."""

    correlation_id: str
    total_slices: int
    dispatched_jobs: tuple[HesExtractJob, ...]


async def request_hes_data(
    ctx: StitchContext,
    cmd: RequestHesDataCommand,
) -> RequestHesDataResult:
    """Dispatches asynchronous time-sliced extraction requests across 3 HES systems.

    Pure function taking typed StitchContext with zero decorators or global state.
    """
    bound_logger = logger.bind(
        tenant_id=ctx.tenant_id,
        trace_id=ctx.trace_id,
        correlation_id=cmd.correlation_id,
    )
    bound_logger.info(
        "request_hes_data_started",
        hes_targets=cmd.hes_targets,
        start_time=cmd.start_time,
        end_time=cmd.end_time,
    )

    start_dt = parse_iso_datetime(cmd.start_time)
    end_dt = parse_iso_datetime(cmd.end_time)

    # 1. Partition date range into atomic daily time slices via injected slicer port
    time_slices = ctx.slicer.slice_daily(start_dt, end_dt)
    dispatched: list[HesExtractJob] = []

    # 2. Fanout requests to each HES system for each time slice
    for hes_conn in cmd.hes_targets:
        for slice_item in time_slices:
            payload: JsonDict = {
                "correlation_id": cmd.correlation_id,
                "start_time": slice_item.start_iso,
                "end_time": slice_item.end_iso,
                "meter_ids": [str(m) for m in cmd.meter_ids],
            }

            # Outbound adapter routes through secure connection manager without exposing credentials
            resp = await ctx.http.dispatch(
                connection_id=hes_conn,
                endpoint="/api/v1/extract_jobs",
                payload=payload,
                method="POST",
            )

            job_id = str(resp.get("job_id", f"job_{hes_conn}_{slice_item.start_iso}"))
            dispatched.append(
                HesExtractJob(
                    hes_target=hes_conn,
                    slice_start=slice_item.start_iso,
                    slice_end=slice_item.end_iso,
                    job_id=job_id,
                    status=str(resp.get("status", "SUBMITTED")),
                )
            )

    bound_logger.info(
        "request_hes_data_completed",
        total_jobs=len(dispatched),
        slices_per_target=len(time_slices),
    )

    return RequestHesDataResult(
        correlation_id=cmd.correlation_id,
        total_slices=len(time_slices),
        dispatched_jobs=tuple(dispatched),
    )


REQUEST_HES_DATA_STITCH = StitchSpec(
    id="energy.request_hes_data",
    trigger="oracle_mdm.meter_readings.requested",
    handler=request_hes_data,
    name="Request HES Data",
    description="Fanout time-sliced data extraction requests across 3 HES systems for Oracle MDM",
    retry=retry_policy(max_attempts=3, initial_backoff=timedelta(seconds=2)),
    step_timeout=timedelta(minutes=5),
    workflow_sla=timedelta(hours=1),
)

__all__ = [
    "REQUEST_HES_DATA_STITCH",
    "HesExtractJob",
    "RequestHesDataCommand",
    "RequestHesDataResult",
    "request_hes_data",
]
