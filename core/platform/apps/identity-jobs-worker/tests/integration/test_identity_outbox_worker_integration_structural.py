import pytest
from identity.domain.constants import IdentityJobName

from identity_jobs_worker.bootstrap.container import WorkerContainer
from identity_jobs_worker.config.settings import get_settings


class FakeJobHandler:
    def __init__(self) -> None:
        self.execution_count = 0

    async def execute(self) -> None:
        self.execution_count += 1


@pytest.mark.asyncio
async def test_structural() -> None:
    settings = get_settings()
    container = WorkerContainer(settings)
    container.wire()

    assert container.outbox_relay is not None
    assert container.jobs_consumer is not None
    assert container.sweeper_job_handler is not None
    assert container.outbox_cleanup_job_handler is not None

    # Verify subscriptions via public handler
    fake_sweeper = FakeJobHandler()
    fake_cleanup = FakeJobHandler()

    container.sweeper_job_handler.execute = fake_sweeper.execute
    container.outbox_cleanup_job_handler.execute = fake_cleanup.execute

    await container.jobs_consumer.handler(
        {"job_name": IdentityJobName.IDENTITY_OUTBOX_SWEEPER.value}
    )
    assert fake_sweeper.execution_count == 1

    await container.jobs_consumer.handler(
        {"job_name": IdentityJobName.IDENTITY_OUTBOX_CLEANUP.value}
    )
    assert fake_cleanup.execution_count == 1

    await container.dispose()
