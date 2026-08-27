import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.scheduling import ScheduledJob


class SchedulerClient:
    """
    Client for interacting with the Platform Scheduler Engine.
    Provides an abstraction over the underlying persistence models for bounded contexts.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register_job(
        self,
        name: str,
        target_queue: str,
        app_namespace: str,
        cron_expression: str | None = None,
        default_timezone: str = "UTC",
        max_retries: int = 3,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """
        Registers a scheduled job with the Platform Scheduler Engine if it does not already exist.
        """
        stmt = select(ScheduledJob).where(
            ScheduledJob.name == name, ScheduledJob.app_namespace == app_namespace
        )
        result = await self.session.execute(stmt)
        existing_job = result.scalar_one_or_none()

        if existing_job:
            existing_job.target_queue = target_queue
            existing_job.cron_expression = cron_expression
            existing_job.timezone = default_timezone
            existing_job.max_retries = max_retries
            return

        now = datetime.now(UTC).replace(tzinfo=None)

        new_job = ScheduledJob(
            id=str(uuid.uuid4()),
            name=name,
            target_queue=target_queue,
            app_namespace=app_namespace,
            cron_expression=cron_expression,
            timezone=default_timezone,
            max_retries=max_retries,
            payload=payload or {},
            status="PENDING",
            created_at=now,
            updated_at=now,
        )
        self.session.add(new_job)
