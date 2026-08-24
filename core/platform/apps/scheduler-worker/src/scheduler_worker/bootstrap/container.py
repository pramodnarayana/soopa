import os
from typing import Any

from dependency_injector import containers, providers
from scheduler.adapters.outbound.database.postgres_job_repository import PostgresJobRepository
from scheduler.adapters.outbound.messaging.sqs_job_dispatcher import SQSJobDispatcher
from scheduler.application.claim_and_execute_jobs_use_case import ClaimAndExecuteJobsUseCase
from scheduler.application.sweep_stuck_jobs_use_case import SweepStuckJobsUseCase

from scheduler_worker.adapters.inbound.workers.scheduler_poller import SchedulerPoller
from scheduler_worker.adapters.outbound.messaging.sqs_job_dispatcher import SqsJobDispatcher


def _validate_positive_int(value: int, name: str) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the Scheduler Engine.
    """

    session_factory: providers.Dependency[Any] = providers.Dependency()

    job_repository = providers.Factory(
        PostgresJobRepository,
        session_factory=session_factory,
    )

    job_dispatcher = providers.Factory(
        SQSJobDispatcher,
        endpoint_url=providers.Callable(os.environ.get, "AWS_ENDPOINT_URL", None),
        region=providers.Callable(os.environ.get, "AWS_REGION", "us-east-1"),
    )

    sweep_use_case = providers.Factory(
        SweepStuckJobsUseCase,
        repository=job_repository,
    )

    claim_use_case = providers.Factory(
        ClaimAndExecuteJobsUseCase,
        repository=job_repository,
        dispatcher=job_dispatcher,
    )

    worker = providers.Factory(
        SchedulerPoller,
        sweep_use_case=sweep_use_case,
        claim_use_case=claim_use_case,
        poll_interval_seconds=providers.Callable(
            _validate_positive_int,
            providers.Callable(
                int, providers.Callable(os.environ.get, "SCHEDULER_POLL_INTERVAL_SECONDS", "5")
            ),
            "poll_interval_seconds",
        ),
        max_concurrent_jobs=providers.Callable(
            _validate_positive_int,
            providers.Callable(
                int, providers.Callable(os.environ.get, "SCHEDULER_MAX_CONCURRENT_JOBS", "10")
            ),
            "max_concurrent_jobs",
        ),
    )
