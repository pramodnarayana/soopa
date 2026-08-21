from datetime import datetime
from typing import Protocol

from ...domain.models import ScheduledJob


class JobRepositoryPort(Protocol):
    async def sweep_stuck_jobs(self, lock_lease_ms: int) -> int: ...

    async def claim_next_jobs(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[ScheduledJob]: ...

    async def reschedule(self, job_id: str, worker_id: str, next_run_at: datetime) -> None: ...

    async def schedule_retry(
        self, job_id: str, worker_id: str, retry_count: int, next_run_at: datetime
    ) -> None: ...

    async def mark_completed(self, job_id: str, worker_id: str) -> None: ...

    async def mark_failed(self, job_id: str, worker_id: str, error_message: str) -> None: ...
