from typing import Any

from dependency_injector import containers, providers
from scheduler.adapters.outbound.database.uow import SqlAlchemySchedulerUnitOfWork
from scheduler.adapters.outbound.messaging.sqs_job_dispatcher import SQSJobDispatcher
from scheduler.application.job_executor_use_case import JobExecutorUseCase
from scheduler.application.job_sweeper_use_case import JobSweeperUseCase

from scheduler_worker.adapters.inbound.workers.scheduler_poller import SchedulerPoller


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the Scheduler Engine.
    """

    config = providers.Configuration()
    session_factory: providers.Dependency[Any] = providers.Dependency()

    uow_factory = providers.Factory(
        SqlAlchemySchedulerUnitOfWork,
        session=providers.Factory(
            lambda session_factory: session_factory(), session_factory=session_factory
        ),
    )

    job_dispatcher = providers.Factory(
        SQSJobDispatcher,
        queue_url_map=providers.Dict(
            {
                "edi-data-plane-jobs.fifo": config.sqs_data_plane_jobs_queue_url,
                "edi-control-plane-jobs.fifo": config.sqs_control_plane_jobs_queue_url,
                "notification-jobs.fifo": config.sqs_notification_jobs_queue_url,
            }
        ),
        endpoint_url=config.aws_endpoint_url,
        region=config.aws_region,
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
        poll_interval_seconds=config.scheduler_poll_interval_seconds,
        max_concurrent_jobs=config.scheduler_max_concurrent_jobs,
    )
