from dataclasses import dataclass
from datetime import datetime
from typing import Any

from scheduler.domain.constants import JobStatus


@dataclass(frozen=True)
class ScheduledJob:
    id: str
    name: str
    target_queue: str | None
    payload: dict[str, Any]
    status: JobStatus
    cron_expression: str | None
    interval_seconds: int | None
    retry_count: int
    max_retries: int
    next_run_at: datetime | None
