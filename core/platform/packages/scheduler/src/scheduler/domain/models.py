from dataclasses import dataclass
from datetime import datetime

from scheduler.domain.constants import JobStatus

type JsonValue = str | int | float | bool | dict[str, "JsonValue"] | list["JsonValue"] | None


@dataclass(frozen=True)
class ScheduledJob:
    id: str
    name: str
    target_queue: str | None
    payload: dict[str, JsonValue]
    status: JobStatus
    cron_expression: str | None
    interval_seconds: int | None
    retry_count: int
    max_retries: int
    next_run_at: datetime | None
