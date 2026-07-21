import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, cast


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


class JobName(StrEnum):
    OUTBOX_SWEEPER = "outbox_sweeper"
    DATA_RETENTION_CLEANUP = "data_retention_cleanup"


@dataclass
class Job:
    name: str
    payload: dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    target_queue: str | None = None
    app_namespace: str | None = None
    next_run_at: datetime | None = None
    interval_seconds: int | None = None
    cron_expression: str | None = None
    timezone: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    locked_at: datetime | None = None
    locked_by: str | None = None

    def calculate_next_run_at(self, now: datetime) -> datetime | None:
        """
        Calculate the next run time based on cron_expression or interval_seconds.
        If neither is provided, returns None.
        """
        import datetime as dt

        if self.cron_expression:
            import zoneinfo

            from croniter import croniter  # type: ignore

            tz = zoneinfo.ZoneInfo(self.timezone) if self.timezone else dt.UTC
            now_tz = now.astimezone(tz)
            itr = croniter(self.cron_expression, now_tz, second_at_beginning=True)
            return cast(dt.datetime, itr.get_next(dt.datetime))

        if self.interval_seconds:
            return now + dt.timedelta(seconds=self.interval_seconds)

        return None

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime | None = None
    updated_at: datetime | None = None
