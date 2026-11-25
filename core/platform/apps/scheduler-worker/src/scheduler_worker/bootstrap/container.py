from collections.abc import Callable, Mapping

from config_sync.domain.enums import ConfigSyncJobName
from config_sync.provider import ConfigSyncProvider
from dependency_injector import containers, providers
from pubsub.adapters.database.sqlalchemy_database_queue_repository import (
    SessionScopeFactory,
    SqlAlchemyDatabaseQueueRepository,
)
from pubsub.domain.enums import PubSubJobName, is_database_queue_uri
from scheduler.adapters.outbound.messaging.database_job_dispatcher import DatabaseJobDispatcher
from scheduler.adapters.outbound.messaging.sqs_job_dispatcher import SQSJobDispatcher
from scheduler.application.job_executor_use_case import JobExecutorUseCase
from scheduler.application.job_sweeper_use_case import JobSweeperUseCase
from scheduler.bootstrap.uow_factory import create_scheduler_uow
from scheduler.domain.scheduled_job import ScheduledJob
from scheduler.ports.outbound.job_dispatcher_port import JobDispatcherPort
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler_worker.adapters.inbound.workers.scheduler_poller import SchedulerPoller


def create_job_dispatcher(
    *,
    session_factory: SessionScopeFactory,
    queue_url_map: Mapping[str, str],
    endpoint_url: str | None = None,
    region: str = "us-east-1",
) -> JobDispatcherPort:
    """Composition root factory selecting DatabaseJobDispatcher for `db://` queues or SQSJobDispatcher for AWS."""
    urls = list(queue_url_map.values())
    if not urls or any(is_database_queue_uri(u) for u in urls):
        queue_repo = SqlAlchemyDatabaseQueueRepository(session_factory=session_factory)
        changelog_repo = ConfigSyncProvider.create_changelog_repository(
            session_factory=session_factory
        )

        async def _handle_platform_queue_cleanup(job: ScheduledJob) -> None:
            raw_days = job.payload.get("retention_days", 7)
            retention_days = raw_days if isinstance(raw_days, int) and raw_days >= 0 else 7
            await queue_repo.cleanup_processed(retention_days=retention_days)

        async def _handle_config_changelog_cleanup(job: ScheduledJob) -> None:
            raw_days = job.payload.get("retention_days", 30)
            retention_days = raw_days if isinstance(raw_days, int) and raw_days >= 0 else 30
            await changelog_repo.cleanup_old_entries(retention_days=retention_days)

        return DatabaseJobDispatcher(
            database_queue=queue_repo,
            queue_url_map=queue_url_map,
            handlers={
                PubSubJobName.PLATFORM_QUEUE_CLEANUP.value: _handle_platform_queue_cleanup,
                ConfigSyncJobName.CONFIG_CHANGELOG_CLEANUP.value: _handle_config_changelog_cleanup,
            },
        )
    return SQSJobDispatcher(
        queue_url_map=dict(queue_url_map),
        endpoint_url=endpoint_url,
        region=region,
    )


class Container(containers.DeclarativeContainer):
    """
    Declarative IoC container for the Scheduler Engine.
    """

    config = providers.Configuration()
    session_factory: providers.Dependency[Callable[[], AsyncSession]] = providers.Dependency()

    uow_factory = providers.Factory(
        create_scheduler_uow,
        session=providers.Factory(
            lambda session_factory: session_factory(), session_factory=session_factory
        ),
    )

    job_dispatcher = providers.Factory(
        create_job_dispatcher,
        session_factory=session_factory,
        queue_url_map=config.sqs_queue_url_map,
        endpoint_url=config.aws_endpoint_url,
        region=config.aws_region,
    )

    sweep_use_case = providers.Factory(
        JobSweeperUseCase,
        uow_factory=uow_factory.provider,
        active_namespaces=config.active_namespaces,
    )

    claim_use_case = providers.Factory(
        JobExecutorUseCase,
        uow_factory=uow_factory.provider,
        dispatcher=job_dispatcher,
        active_namespaces=config.active_namespaces,
    )

    worker = providers.Factory(
        SchedulerPoller,
        sweep_use_case=sweep_use_case,
        claim_use_case=claim_use_case,
        poll_interval_seconds=config.scheduler_poll_interval_seconds,
        max_concurrent_jobs=config.scheduler_max_concurrent_jobs,
    )
