"""Unit tests for NotifyOutboxRelay and stateless SqlAlchemyShardedOutboxRepository."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence

import pytest
from database.listener import NotifyCallback, NotifyListenerConnectionPort
from database.models.common import OutboxMixin
from database.router import DatabaseRouterPort
from database.types import GlobalSession, TenantSession
from outbox.adapters.inbound.notify_outbox_relay import NotifyOutboxRelay
from outbox.adapters.outbound.sqlalchemy_sharded_outbox_repository import (
    SqlAlchemyShardedOutboxRepository,
)
from outbox.application.outbox_processor_use_case import OutboxProcessorUseCase
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from outbox.ports.outbox_repository_port import OutboxRepositoryPort
from seedwork.events import EventEnvelope
from sqlalchemy.orm import DeclarativeBase


class _TestBase(DeclarativeBase):
    pass


class _DummyOutboxModel(_TestBase, OutboxMixin):
    __tablename__ = "dummy_outbox"


class _FakeListenerConnection(NotifyListenerConnectionPort):
    def __init__(self) -> None:
        self.callbacks: dict[str, NotifyCallback] = {}
        self.closed = False

    async def add_listener(self, channel: str, callback: NotifyCallback) -> None:
        self.callbacks[channel] = callback

    async def remove_listener(self, channel: str, callback: NotifyCallback) -> None:
        del callback
        self.callbacks.pop(channel, None)

    async def close(self) -> None:
        self.closed = True

    def is_closed(self) -> bool:
        return self.closed


class _FakeOutboxRepo(OutboxRepositoryPort):
    def __init__(self) -> None:
        self.claim_calls = 0

    async def claim_next_events(
        self, worker_id: str, limit: int, lock_lease_ms: int
    ) -> list[EventEnvelope]:
        del worker_id, limit, lock_lease_ms
        self.claim_calls += 1
        return []

    async def sweep_stuck_events(self, lock_lease_ms: int) -> int:
        del lock_lease_ms
        return 0

    async def mark_completed(self, event_id: str, worker_id: str) -> None:
        del event_id, worker_id

    async def mark_completed_batch(self, event_ids: Sequence[str], worker_id: str) -> None:
        del event_ids, worker_id

    async def mark_failed(self, event_id: str, worker_id: str, error_message: str) -> None:
        del event_id, worker_id, error_message

    async def mark_failed_batch(
        self, event_ids: Sequence[str], worker_id: str, error_message: str
    ) -> None:
        del event_ids, worker_id, error_message


class _NoopPublisher(OutboxPublisherPort):
    async def publish(self, event: EventEnvelope) -> None:
        del event


class _RecordingShardedRepo(SqlAlchemyShardedOutboxRepository[_DummyOutboxModel]):
    def __init__(self, router: DatabaseRouterPort) -> None:
        super().__init__(
            router,
            model_cls=_DummyOutboxModel,
            app_slug="edi",
            source="edi",
        )
        self.completed_calls: list[tuple[str, str, tuple[str, ...], str]] = []
        self.failed_calls: list[tuple[str, str, tuple[str, ...], str, str]] = []

    async def mark_shard_completed_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
    ) -> None:
        self.completed_calls.append((shard_name, shard_dsn, tuple(event_ids), worker_id))

    async def mark_shard_failed_batch(
        self,
        *,
        shard_name: str,
        shard_dsn: str,
        event_ids: Sequence[str],
        worker_id: str,
        error_message: str,
    ) -> None:
        self.failed_calls.append(
            (shard_name, shard_dsn, tuple(event_ids), worker_id, error_message)
        )


class _StubRouter(DatabaseRouterPort):
    def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        raise NotImplementedError

    def global_session_scope(self):
        raise NotImplementedError

    def get_tenant_session(
        self, tenant_id: str, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        raise NotImplementedError

    def get_shard_session(
        self, shard_key: str, shard_url: str
    ) -> AsyncGenerator[TenantSession, None]:
        raise NotImplementedError

    async def get_all_shards(self, app_slug: str | None = None) -> list[tuple[str, str]]:
        assert app_slug == "edi"
        return [("edi_shard_1", "dsn://s1"), ("edi_shard_2", "dsn://s2")]

    async def close_all(self) -> None:
        return None


@pytest.mark.asyncio
async def test_notify_outbox_relay_wakes_and_closes_cleanly() -> None:
    fake_conn = _FakeListenerConnection()
    repo = _FakeOutboxRepo()
    processor = OutboxProcessorUseCase(repository=repo, publisher=_NoopPublisher())

    async def _connect(url: str) -> NotifyListenerConnectionPort:
        assert url == "dsn://test_global"
        return fake_conn

    relay = NotifyOutboxRelay(
        processor=processor,
        database_url="dsn://test_global",
        listen_channel="test_channel",
        fallback_poll_interval=30,
        listener_connector=_connect,
    )
    relay.start()
    await asyncio.sleep(0.05)

    assert "test_channel" in fake_conn.callbacks
    initial_claims = repo.claim_calls
    assert initial_claims >= 1

    fake_conn.callbacks["test_channel"](fake_conn, 1234, "test_channel", "wake")
    await asyncio.sleep(0.05)
    assert repo.claim_calls > initial_claims

    await relay.stop()
    assert fake_conn.closed is True
    assert "test_channel" not in fake_conn.callbacks


@pytest.mark.asyncio
async def test_sharded_outbox_repository_is_stateless_and_fans_out_batches() -> None:
    repo = _RecordingShardedRepo(_StubRouter())
    assert not hasattr(repo, "_event_shard_map")

    await repo.mark_completed_batch(["evt_1", "evt_2"], "worker_a")
    assert sorted(repo.completed_calls) == [
        ("edi_shard_1", "dsn://s1", ("evt_1", "evt_2"), "worker_a"),
        ("edi_shard_2", "dsn://s2", ("evt_1", "evt_2"), "worker_a"),
    ]

    await repo.mark_failed_batch(["evt_3"], "worker_a", "boom")
    assert sorted(repo.failed_calls) == [
        ("edi_shard_1", "dsn://s1", ("evt_3",), "worker_a", "boom"),
        ("edi_shard_2", "dsn://s2", ("evt_3",), "worker_a", "boom"),
    ]
