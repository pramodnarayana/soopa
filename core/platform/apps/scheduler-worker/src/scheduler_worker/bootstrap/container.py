import os
from typing import Any

from dependency_injector import containers, providers
from scheduler.adapters.outbound.database.uow import SqlAlchemySchedulerUnitOfWork
from scheduler.adapters.outbound.messaging.sqs_job_dispatcher import SQSJobDispatcher
from scheduler.application.job_executor_use_case import JobExecutorUseCase
from scheduler.application.job_sweeper_use_case import JobSweeperUseCase

from scheduler_worker.adapters.inbound.workers.scheduler_poller import SchedulerPoller


def _validate_positive_int(value: int, name: str) -> int:
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the Scheduler Engine.
    """

    session_factory: providers.Dependency[Any] = providers.Dependency()

    uow_factory = providers.Factory(
        SqlAlchemySchedulerUnitOfWork,
        session=providers.Factory(
            lambda session_factory: session_factory(), session_factory=session_factory
        ),
    )

    job_dispatcher = providers.Factory(
        SQSJobDispatcher,
        endpoint_url=providers.Callable(os.environ.get, "AWS_ENDPOINT_URL", None),
        region=providers.Callable(os.environ.get, "AWS_REGION", "us-east-1"),
    )

    sweep_use_case = providers.Factory(
        JobSweeperUseCase,
        uow_factory=uow_factory.provider,
    )

    claim_use_case = providers.Factory(
        JobExecutorUseCase,
        uow_factory=uow_factory.provider,
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
