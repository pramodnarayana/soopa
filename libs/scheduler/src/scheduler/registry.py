from dataclasses import dataclass

from scheduler.domain.models import JobName


@dataclass(frozen=True)
class JobDefinition:
    """
    Canonical definition of a platform system job.
    Drives both database seeding and API-level validation of job configuration.
    """

    name: JobName
    target_queue: str | None = None
    app_namespace: str | None = None
    default_interval_seconds: int | None = None
    min_interval_seconds: int | None = None
    max_interval_seconds: int | None = None
    default_cron_expression: str | None = None
    default_timezone: str | None = None
    max_retries: int = 3


# Central registry of all platform-managed background jobs.
# To register a new system job, append a JobDefinition here.
SYSTEM_JOB_REGISTRY: list[JobDefinition] = [
    JobDefinition(
        name=JobName.OUTBOX_SWEEPER,
        target_queue="edi-orchestrator-jobs",
        app_namespace="EDI",
        default_interval_seconds=60,
        min_interval_seconds=10,
        max_interval_seconds=300,
    ),
    JobDefinition(
        name=JobName.DATA_RETENTION_CLEANUP,
        target_queue="edi-orchestrator-jobs",
        app_namespace="EDI",
        default_cron_expression="0 2 * * *",  # 2 AM daily
        default_timezone="UTC",
    ),
]
