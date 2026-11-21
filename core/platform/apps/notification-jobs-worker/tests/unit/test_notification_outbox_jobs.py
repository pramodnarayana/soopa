import pytest
from notification.domain.constants import NotificationCleanupJobName
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.application.outbox_sweeper_use_case import OutboxSweeperUseCase
from outbox.ports.outbox_cleanup_repository_port import OutboxCleanupRepositoryPort
from outbox.testing.fakes import (
    FakeOutboxCleanupRepository,
    FakeOutboxPublisher,
    FakeOutboxRepository,
)

from notification_jobs_worker.adapters.inbound.jobs.notification_outbox_cleanup_job import (
    NotificationOutboxCleanupJobHandler,
)
from notification_jobs_worker.adapters.inbound.jobs.notification_outbox_sweeper_job import (
    NotificationOutboxSweeperJobHandler,
)
from notification_jobs_worker.bootstrap.container import WorkerContainer, init_job_dispatcher


class FailingCleanupRepository(OutboxCleanupRepositoryPort):
    """Deterministic failure repository fake for verifying exception bubbling and logging."""

    async def cleanup_outbox(self, retention_days: int) -> int:
        raise RuntimeError("Database cleanup execution failure")


@pytest.mark.asyncio
async def test_notification_outbox_cleanup_job_handler_success() -> None:
    repo = FakeOutboxCleanupRepository()
    use_case = OutboxCleanerUseCase(repository=repo, retention_days=5)
    handler = NotificationOutboxCleanupJobHandler(use_case=use_case)

    await handler.execute()

    assert repo.cleanup_calls == [5]


@pytest.mark.asyncio
async def test_notification_outbox_cleanup_job_handler_failure_re_raises() -> None:
    repo = FailingCleanupRepository()
    use_case = OutboxCleanerUseCase(repository=repo, retention_days=3)
    handler = NotificationOutboxCleanupJobHandler(use_case=use_case)

    with pytest.raises(RuntimeError, match="Database cleanup execution failure"):
        await handler.execute()


@pytest.mark.asyncio
async def test_notification_outbox_sweeper_job_handler_success() -> None:
    repo = FakeOutboxRepository()
    publisher = FakeOutboxPublisher()
    use_case = OutboxSweeperUseCase(repository=repo, publisher=publisher)
    handler = NotificationOutboxSweeperJobHandler(use_case=use_case)

    await handler.execute()

    assert repo.stuck_events_swept > 0


@pytest.mark.asyncio
async def test_init_job_dispatcher_subscribes_and_dispatches() -> None:
    cleanup_repo = FakeOutboxCleanupRepository()
    cleanup_use_case = OutboxCleanerUseCase(repository=cleanup_repo, retention_days=3)
    cleanup_handler = NotificationOutboxCleanupJobHandler(use_case=cleanup_use_case)

    sweeper_repo = FakeOutboxRepository()
    sweeper_publisher = FakeOutboxPublisher()
    sweeper_use_case = OutboxSweeperUseCase(
        repository=sweeper_repo,
        publisher=sweeper_publisher,
    )
    sweeper_handler = NotificationOutboxSweeperJobHandler(use_case=sweeper_use_case)

    dispatcher = init_job_dispatcher(
        cleanup_handler=cleanup_handler,
        sweeper_handler=sweeper_handler,
    )

    # 1. Dispatch cleanup job
    await dispatcher.dispatch(
        {
            "job_name": NotificationCleanupJobName.NOTIFICATION_OUTBOX_CLEANUP.value,
            "payload": {},
        }
    )
    assert cleanup_repo.cleanup_calls == [3]

    # 2. Dispatch sweeper job
    await dispatcher.dispatch(
        {
            "job_name": NotificationCleanupJobName.NOTIFICATION_OUTBOX_SWEEPER.value,
            "payload": {},
        }
    )
    assert sweeper_repo.stuck_events_swept > 0


def test_container_job_providers_instantiation() -> None:
    container = WorkerContainer()
    assert container.outbox_cleanup_job_handler is not None
    assert container.outbox_sweeper_job_handler is not None
    assert container.job_dispatcher is not None
