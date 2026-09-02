from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from seedwork.constants import SystemIdPrefix
from seedwork.utils import generate_id


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PAUSED = "PAUSED"


class JobName(StrEnum):
    EDI_ORCHESTRATOR_OUTBOX_SWEEPER = "edi_orchestrator_outbox_sweeper"
    EDI_PROVISIONING_OUTBOX_SWEEPER = "edi_provisioning_outbox_sweeper"
    DATA_RETENTION_CLEANUP = "data_retention_cleanup"
    UCP_OUTBOX_SWEEPER = "ucp_outbox_sweeper"
    UCP_DATA_RETENTION_CLEANUP = "ucp_data_retention_cleanup"
    EDI_CONTROL_PLANE_OUTBOX_CLEANUP = "EDI_CONTROL_PLANE_OUTBOX_CLEANUP"
    EDI_DATA_PLANE_OUTBOX_CLEANUP = "EDI_DATA_PLANE_OUTBOX_CLEANUP"
    EDI_IDEMPOTENCY_CLEANUP = "EDI_IDEMPOTENCY_CLEANUP"
    EDI_AUDIT_LOG_CLEANUP = "EDI_AUDIT_LOG_CLEANUP"


class AppNamespace(StrEnum):
    EDI = "EDI"


class TargetQueue(StrEnum):
    EDI_ORCHESTRATOR_JOBS = "edi-orchestrator-jobs"


class Timezone(StrEnum):
    UTC = "UTC"


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
    lease_expires_at: datetime | None = None
    owner_token: str | None = None
    id: str = field(default_factory=lambda: generate_id(SystemIdPrefix.JOB))
    created_at: datetime | None = None
    updated_at: datetime | None = None
