from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class ScheduledJob(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    target_queue: str | None
    payload: dict[str, Any]
    status: str
    cron_expression: str | None
    interval_seconds: int | None
    retry_count: int
    max_retries: int
    next_run_at: datetime | None
