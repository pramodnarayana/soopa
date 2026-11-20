import asyncio
from collections.abc import AsyncGenerator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from types import TracebackType

import pytest
from database.router import DatabaseRouterPort
from database.types import GlobalSession, TenantSession
from outbox.adapters.inbound.multi_shard_outbox_drain_relay import MultiShardOutboxDrainRelay
from outbox.ports.outbox_relay_port import OutboxRelayPort
from pubsub.aws.sqs_consumer_manager import SqsConsumerManager
from pubsub.message import AckableMessage
from pubsub.ports.message_consumer_port import MessageConsumerPort
from seedwork.domain.types import JsonDict

from edi_dp_jobs_worker.bootstrap.container import WorkerContainer
from edi_dp_jobs_worker.main import EdiDpJobsWorkerModule
from edi_dp_jobs_worker.settings import WorkerSettings


class FakeDatabaseRouter(DatabaseRouterPort):
    def __init__(self) -> None:
        self.closed = False
        self.shards: list[tuple[str, str]] = [("shard_1", "postgresql://localhost/shard1")]

    async def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        if False:
            yield  # pragma: no cover

    def global_session_scope(self) -> AbstractAsyncContextManager[GlobalSession]:
        raise NotImplementedError

    async def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        if False:
            yield  # pragma: no cover

    async def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        if False:
            yield  # pragma: no cover

    async def get_all_shards(self, app_slug: str | None = None) -> list[tuple[str, str]]:
        return self.shards

    async def close_all(self) -> None:
        self.closed = True


class FakeOutboxRelay(OutboxRelayPort):
    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.task: asyncio.Task[object] | None = None

    def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    def background_tasks(self) -> list[asyncio.Task[object]]:
        return [self.task] if self.task is not None else []


class FakeMessageConsumer(MessageConsumerPort):
    async def __aenter__(self) -> MessageConsumerPort:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    @asynccontextmanager
    async def poll_raw_message(self) -> AsyncGenerator[AckableMessage | None, None]:
        await asyncio.sleep(10)
        yield None


async def _noop_handler(msg: JsonDict) -> None:
    pass


def test_worker_container_wire() -> None:
    router = FakeDatabaseRouter()
    settings = WorkerSettings()
    container = WorkerContainer(settings=settings, db_router=router)

    container.wire()

    assert container.dp_outbox_relay is not None
    assert isinstance(container.dp_outbox_relay, MultiShardOutboxDrainRelay)
    assert container.dp_outbox_relay.batch_size == 500
    assert container.dp_outbox_relay.poll_interval_seconds == 0.2
    assert container.dp_manager is not None
    assert container.dp_sweeper_job_handler is not None
    assert container.dp_cleanup_job_handler is not None
    assert container.retention_cleanup_job_handler is not None


@pytest.mark.asyncio
async def test_worker_container_lifecycle() -> None:
    router = FakeDatabaseRouter()
    container = WorkerContainer(db_router=router)

    fake_relay = FakeOutboxRelay()
    fake_consumer = FakeMessageConsumer()
    consumer_manager = SqsConsumerManager(
        consumer=fake_consumer,
        handler=_noop_handler,
        queue_name="test-queue",
    )

    container.dp_outbox_relay = fake_relay
    container.dp_manager = consumer_manager

    await container.start()
    assert fake_relay.started is True
    assert consumer_manager.is_running is True

    await container.dispose()
    assert fake_relay.stopped is True
    assert consumer_manager.is_running is False
    assert router.closed is True


@pytest.mark.asyncio
async def test_worker_module_background_tasks() -> None:
    router = FakeDatabaseRouter()
    container = WorkerContainer(db_router=router)

    fake_relay = FakeOutboxRelay()
    fake_consumer = FakeMessageConsumer()
    consumer_manager = SqsConsumerManager(
        consumer=fake_consumer,
        handler=_noop_handler,
        queue_name="test-queue",
    )

    stop_event = asyncio.Event()

    async def _dummy_coro() -> None:
        await stop_event.wait()

    relay_task: asyncio.Task[object] = asyncio.create_task(_dummy_coro())
    fake_relay.task = relay_task

    container.dp_outbox_relay = fake_relay
    container.dp_manager = consumer_manager

    consumer_manager.start()
    module = EdiDpJobsWorkerModule(container=container)
    tasks = module.get_background_tasks()

    assert len(tasks) >= 2
    assert relay_task in tasks

    await consumer_manager.stop()
    stop_event.set()
    await relay_task
