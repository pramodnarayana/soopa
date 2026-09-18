from identity.domain.constants import IdentityJobName

from identity_jobs_worker.bootstrap.container import WorkerContainer
from identity_jobs_worker.config.settings import get_settings


def test_structural() -> None:
    settings = get_settings()
    container = WorkerContainer(settings)
    container.wire()

    assert container.outbox_relay is not None
    assert container.jobs_consumer is not None
    assert container.sweeper_job_handler is not None
    assert container.outbox_cleanup_job_handler is not None

    # Verify subscriptions
    dispatcher = container.jobs_consumer.handler.__self__  # type: ignore[attr-defined]
    handlers = getattr(dispatcher, "handlers", getattr(dispatcher, "_handlers", {}))

    assert IdentityJobName.IDENTITY_OUTBOX_SWEEPER.value in handlers
    assert IdentityJobName.IDENTITY_OUTBOX_CLEANUP.value in handlers
