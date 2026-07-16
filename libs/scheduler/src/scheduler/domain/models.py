import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class Job:
    name: str
    payload: dict[str, Any]
    status: JobStatus = JobStatus.PENDING
    next_run_at: datetime | None = None
    retry_count: int = 0
    max_retries: int = 3
    locked_at: datetime | None = None
    locked_by: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    created_at: datetime | None = None
    updated_at: datetime | None = None
