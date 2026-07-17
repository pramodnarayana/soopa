import abc
import uuid
from datetime import datetime
from typing import Any

from scheduler.domain.models import Job


class JobRepositoryPort(abc.ABC):
    @abc.abstractmethod
    async def claim_next_jobs(self, worker_id: str, limit: int) -> list[Job]:
        pass

    @abc.abstractmethod
    async def mark_completed(self, job_id: uuid.UUID) -> None:
        pass

    @abc.abstractmethod
    async def mark_failed(self, job_id: uuid.UUID, error: str) -> None:
        pass

    @abc.abstractmethod
    async def schedule_job(
        self,
        name: str,
        payload: dict[str, Any],
        next_run_at: datetime | None = None,
        interval_seconds: int | None = None,
    ) -> Job:
        pass

    @abc.abstractmethod
    async def reschedule(self, job_id: uuid.UUID, next_run_at: datetime) -> None:
        pass

    @abc.abstractmethod
    async def schedule_retry(self, job_id: uuid.UUID, next_run_at: datetime) -> None:
        pass
