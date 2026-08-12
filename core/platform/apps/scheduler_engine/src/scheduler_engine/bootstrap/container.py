import os
from typing import Any

from dependency_injector import containers, providers

from scheduler_engine.adapters.outbound.dummy_job_dispatcher import DummyJobDispatcher
from scheduler_engine.adapters.outbound.postgres_job_repository import SqlAlchemyJobRepository
from scheduler_engine.worker import SchedulerWorker


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
        SqlAlchemyJobRepository,
        session_factory=session_factory,
    )

    job_dispatcher = providers.Factory(
        DummyJobDispatcher,
    )

    worker = providers.Factory(
        SchedulerWorker,
        repository=job_repository,
        dispatcher=job_dispatcher,
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
