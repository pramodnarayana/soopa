import pytest
from identity.domain.constants import IdentityOutboxSource
from outbox.adapters.inbound.outbox_drain_relay import OutboxDrainRelay
from pubsub.config import PlatformPubSubSettings
from seedwork.infra.config_models import PlatformDatabaseSettings

from identity_jobs_worker.adapters.inbound.jobs.identity_outbox_sweeper_job import (
    IdentityOutboxSweeperJobHandler,
)
from identity_jobs_worker.bootstrap.container import WorkerContainer
from identity_jobs_worker.config.settings import (
    AppSettings,
    IdentityOutboxAwsSettings,
    SqsSettings,
)


class FailingUseCase:
    async def execute(self) -> None:
        raise RuntimeError("outbox failure")


@pytest.mark.asyncio
async def test_outbox_sweeper_job_handler_propagates_use_case_failure() -> None:
    use_case = FailingUseCase()

    with pytest.raises(RuntimeError, match="outbox failure"):
        await IdentityOutboxSweeperJobHandler(use_case).execute()


@pytest.mark.asyncio
async def test_identity_worker_container_wires_outbox_drain_relay() -> None:
    settings = AppSettings(
        database=PlatformDatabaseSettings(global_url="sqlite+aiosqlite:///:memory:"),
        aws=IdentityOutboxAwsSettings(sns_identity_events_topic_arn="db://platform-events-topic"),
        sqs=SqsSettings(identity_jobs_queue_url="db://identity-jobs-queue"),
        pubsub=PlatformPubSubSettings(transport="db"),
    )
    container = WorkerContainer(settings)
    try:
        container.wire()
        assert isinstance(container.outbox_relay, OutboxDrainRelay)
        assert container.outbox_relay.relay_name == IdentityOutboxSource.IDENTITY.value
    finally:
        await container.dispose()
