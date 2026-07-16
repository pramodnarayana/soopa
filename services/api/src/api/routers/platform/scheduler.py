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
    next_run_at: datetime | None
    locked_at: datetime | None
    locked_by: str | None
    retry_count: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


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
    import datetime
    import uuid

    from database.models.scheduled_job import ScheduledJob

    async with uow:
        await uow.platform_settings.set_config(key, request.value)

        # Event-driven scheduler integration
        if key == "outbox_sweeper_enabled":
            stmt = select(ScheduledJob).where(ScheduledJob.name == "outbox_sweeper")
            result = await uow.global_session.execute(stmt)
            job = result.scalar_one_or_none()
            now = datetime.datetime.now(datetime.UTC)

            if request.value is True:
                if job:
                    job.next_run_at = now
                    job.status = "PENDING"
                else:
                    # Get interval if exists
                    interval_cfg = await uow.platform_settings.get_config(
                        "outbox_sweeper_interval_seconds"
                    )
                    interval = interval_cfg if interval_cfg is not None else 60

                    new_job = ScheduledJob(
                        id=uuid.uuid4(),
                        name="outbox_sweeper",
                        payload={"interval_seconds": int(interval)},
                        status="PENDING",
                        next_run_at=now,
                        retry_count=0,
                        max_retries=3,
                        created_at=now,
                        updated_at=now,
                    )
                    uow.global_session.add(new_job)
            else:
                if job:
                    await uow.global_session.delete(job)

        elif key == "outbox_sweeper_interval_seconds":
            stmt = select(ScheduledJob).where(ScheduledJob.name == "outbox_sweeper")
            result = await uow.global_session.execute(stmt)
            job = result.scalar_one_or_none()
            if job:
                payload = dict(job.payload) if job.payload else {}
                payload["interval_seconds"] = int(str(request.value))
                job.payload = payload

        await uow.commit()
        return ConfigResponse(key=key, value=request.value)
