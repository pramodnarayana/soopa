import uuid
from datetime import datetime
from typing import Any

from database.models.scheduled_job import ScheduledJob
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from api.core.uow import UnitOfWork
from api.dependencies import get_uow

router = APIRouter(prefix="/scheduler", tags=["Platform Scheduler"])


class JobResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    target_queue: str | None
    app_namespace: str | None
    cron_expression: str | None
    timezone: str | None
    next_run_at: datetime | None
    locked_at: datetime | None
    locked_by: str | None
    interval_seconds: int | None
    min_interval_seconds: int | None = None
    max_interval_seconds: int | None = None
    retry_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobCreateRequest(BaseModel):
    name: str
    interval_seconds: int = 60
    payload: dict[str, Any] = {}


class JobUpdateRequest(BaseModel):
    interval_seconds: int | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    status: str | None = None


class ConfigUpdateRequest(BaseModel):
    value: dict[str, Any] | list[Any] | str | int | bool | None


class ConfigResponse(BaseModel):
    key: str
    value: Any


@router.get("/jobs", response_model=list[JobResponse])
async def list_jobs(uow: UnitOfWork = Depends(get_uow)) -> list[JobResponse]:
    """List all scheduled background jobs (Admin Only)."""
    async with uow:
        stmt = select(ScheduledJob).order_by(ScheduledJob.created_at.desc())
        result = await uow.global_session.execute(stmt)
        jobs = result.scalars().all()
        return [JobResponse.model_validate(job) for job in jobs]


@router.post("/jobs", response_model=JobResponse)
async def create_job(request: JobCreateRequest, uow: UnitOfWork = Depends(get_uow)) -> JobResponse:
    """Create a new scheduled background job."""
    from datetime import UTC

    from fastapi import HTTPException
    from scheduler.domain.models import JobStatus
    from sqlalchemy.exc import IntegrityError

    now = datetime.now(UTC)

    from scheduler.registry import SYSTEM_JOB_REGISTRY

    job_def = next((j for j in SYSTEM_JOB_REGISTRY if j.name.value == request.name), None)
    if not job_def:
        raise HTTPException(
            status_code=422, detail=f"Job '{request.name}' is not a registered system job."
        )

    if not job_def.target_queue:
        raise HTTPException(
            status_code=422, detail=f"Job '{request.name}' has no configured target queue."
        )

    async with uow:
        try:
            async with uow.global_session.begin_nested():
                new_job = ScheduledJob(
                    id=uuid.uuid4(),
                    name=request.name,
                    payload=request.payload,
                    interval_seconds=request.interval_seconds,
                    status=JobStatus.PENDING.value,
                    next_run_at=now,
                    target_queue=job_def.target_queue,
                    app_namespace=job_def.app_namespace,
                    min_interval_seconds=job_def.min_interval_seconds,
                    max_interval_seconds=job_def.max_interval_seconds,
                    retry_count=0,
                    max_retries=job_def.max_retries,
                    created_at=now,
                    updated_at=now,
                )
                uow.global_session.add(new_job)
                await uow.global_session.flush()
        except IntegrityError as e:
            raise HTTPException(
                status_code=409, detail=f"Job '{request.name}' already exists"
            ) from e

        await uow.commit()
        return JobResponse.model_validate(new_job)


@router.put("/jobs/{name}", response_model=JobResponse)
async def update_job(
    name: str, request: JobUpdateRequest, uow: UnitOfWork = Depends(get_uow)
) -> JobResponse:
    """Update a specific scheduled job."""
    from fastapi import HTTPException
    from sqlalchemy import select

    async with uow:
        stmt = select(ScheduledJob).where(ScheduledJob.name == name)
        result = await uow.global_session.execute(stmt)
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{name}' not found")

        if request.interval_seconds is not None:
            if request.interval_seconds <= 0:
                raise HTTPException(status_code=422, detail="Interval must be positive")
            if (
                job.min_interval_seconds is not None
                and request.interval_seconds < job.min_interval_seconds
            ):
                raise HTTPException(status_code=422, detail="Interval too low")
            if (
                job.max_interval_seconds is not None
                and request.interval_seconds > job.max_interval_seconds
            ):
                raise HTTPException(status_code=422, detail="Interval too high")

            job.interval_seconds = request.interval_seconds
            job.cron_expression = None
            job.timezone = None

        if request.cron_expression is not None:
            from croniter import croniter  # type: ignore

            if not croniter.is_valid(request.cron_expression):
                raise HTTPException(status_code=422, detail="Invalid cron expression")

            job.cron_expression = request.cron_expression
            if request.timezone is not None:
                import zoneinfo

                try:
                    zoneinfo.ZoneInfo(request.timezone)
                    job.timezone = request.timezone
                except zoneinfo.ZoneInfoNotFoundError as e:
                    raise HTTPException(status_code=422, detail="Invalid timezone") from e

            job.interval_seconds = None

        if request.status is not None:
            from datetime import UTC, datetime

            from scheduler.domain.models import JobStatus

            if request.status not in [s.value for s in JobStatus]:
                raise HTTPException(status_code=422, detail="Invalid status")

            if job.status == JobStatus.PAUSED.value and request.status == JobStatus.PENDING.value:
                job.next_run_at = datetime.now(UTC)

            job.status = request.status

        import uuid

        from database.models.control_plane import SystemAuditLog

        audit_log = SystemAuditLog(
            trace_id=uuid.uuid4(),
            tenant_id=0,
            event=f"SCHEDULER_JOB_UPDATED: {name}",
            status="SUCCESS",
        )
        uow.global_session.add(audit_log)

        await uow.global_session.flush()
        await uow.commit()

        return JobResponse.model_validate(job)


@router.delete("/jobs/{name}", status_code=204)
async def delete_job(name: str, uow: UnitOfWork = Depends(get_uow)) -> None:
    """Delete a scheduled background job."""
    from fastapi import HTTPException
    from sqlalchemy import select

    async with uow:
        stmt = select(ScheduledJob).where(ScheduledJob.name == name)
        result = await uow.global_session.execute(stmt)
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail=f"Job '{name}' not found")

        await uow.global_session.delete(job)
        await uow.commit()


@router.get("/config", response_model=list[ConfigResponse])
async def get_all_config(uow: UnitOfWork = Depends(get_uow)) -> list[ConfigResponse]:
    """Get all platform configuration values."""
    from database.models.platform_settings import PlatformSettings

    async with uow:
        stmt = select(PlatformSettings).order_by(PlatformSettings.key)
        result = await uow.global_session.execute(stmt)
        configs = result.scalars().all()
        return [ConfigResponse(key=c.key, value=c.value) for c in configs]


@router.get("/config/{key}", response_model=ConfigResponse)
async def get_config(key: str, uow: UnitOfWork = Depends(get_uow)) -> ConfigResponse:
    """Get a specific platform configuration value."""
    async with uow:
        val = await uow.platform_settings.get_config(key)
        return ConfigResponse(key=key, value=val)


@router.put("/config/{key}", response_model=ConfigResponse)
async def update_config(
    key: str, request: ConfigUpdateRequest, uow: UnitOfWork = Depends(get_uow)
) -> ConfigResponse:
    """Update a platform configuration value."""
    async with uow:
        await uow.platform_settings.set_config(key, request.value)
        await uow.commit()
        return ConfigResponse(key=key, value=request.value)
