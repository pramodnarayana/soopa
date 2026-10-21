"""Unit tests for SqlAlchemyStreamStateRepository."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest
from ip.adapters.outbound.database.models.outbox_model import IpOutboxRecord
from ip.adapters.outbound.database.models.stream_state_model import ConnectionStreamStateRecord
from ip.adapters.outbound.database.stream_state_repository import SqlAlchemyStreamStateRepository
from ip.domain.models.stream_state import ConnectionStreamState
from sqlalchemy.ext.asyncio import AsyncSession


class FakeScalarResult:
    def __init__(self, item: Any) -> None:
        self._item = item

    def scalar_one_or_none(self) -> Any:
        return self._item

    def scalars(self) -> FakeScalarResult:
        return self

    def all(self) -> list[Any]:
        if isinstance(self._item, list):
            return self._item
        return [self._item] if self._item is not None else []


class FakeAsyncSession:
    def __init__(self, query_result: Any = None) -> None:
        self.query_result = query_result
        self.added_records: list[Any] = []
        self.flushed = False
        self.executed_statements: list[Any] = []

    async def execute(self, statement: Any) -> FakeScalarResult:
        self.executed_statements.append(statement)
        return FakeScalarResult(self.query_result)

    def add(self, instance: Any) -> None:
        self.added_records.append(instance)

    async def flush(self) -> None:
        self.flushed = True


def test_to_domain_model_mapping() -> None:
    now = datetime.now(UTC)
    record = ConnectionStreamStateRecord(
        id="ip_cst_12345",
        tenant_id="tenant_abc",
        connection_id="conn_xyz",
        stream_name="invoices",
        cursor_field="updated_at",
        cursor_value="2026-10-20T12:00:00Z",
        records_synced_count=150,
        last_synced_at=now,
    )

    domain = SqlAlchemyStreamStateRepository._to_domain_model(record)
    assert domain.id == "ip_cst_12345"
    assert domain.tenant_id == "tenant_abc"
    assert domain.connection_id == "conn_xyz"
    assert domain.stream_name == "invoices"
    assert domain.cursor_field == "updated_at"
    assert domain.cursor_value == "2026-10-20T12:00:00Z"
    assert domain.records_synced_count == 150
    assert domain.last_synced_at == now


def test_update_record_from_domain() -> None:
    now = datetime.now(UTC)
    record = ConnectionStreamStateRecord(
        id="ip_cst_12345",
        tenant_id="tenant_abc",
        connection_id="conn_xyz",
        stream_name="invoices",
        cursor_field="id",
        cursor_value="10",
        records_synced_count=10,
        last_synced_at=now,
    )
    domain = ConnectionStreamState(
        id="ip_cst_12345",
        tenant_id="tenant_abc",
        connection_id="conn_xyz",
        stream_name="invoices",
        cursor_field="id",
        cursor_value="25",
        records_synced_count=25,
        last_synced_at=now,
    )

    SqlAlchemyStreamStateRepository._update_record_from_domain(record, domain)
    assert record.cursor_value == "25"
    assert record.records_synced_count == 25


@pytest.mark.asyncio
async def test_get_by_stream_found() -> None:
    now = datetime.now(UTC)
    record = ConnectionStreamStateRecord(
        id="ip_cst_1",
        tenant_id="t1",
        connection_id="c1",
        stream_name="orders",
        cursor_field="created_at",
        cursor_value="2026-01-01",
        records_synced_count=5,
        last_synced_at=now,
    )
    session = FakeAsyncSession(query_result=record)
    repo = SqlAlchemyStreamStateRepository(cast(AsyncSession, session))

    result = await repo.get_by_stream("t1", "c1", "orders")
    assert result is not None
    assert result.stream_name == "orders"
    assert result.cursor_value == "2026-01-01"


@pytest.mark.asyncio
async def test_get_by_stream_not_found() -> None:
    session = FakeAsyncSession(query_result=None)
    repo = SqlAlchemyStreamStateRepository(cast(AsyncSession, session))

    result = await repo.get_by_stream("t1", "c1", "missing")
    assert result is None


@pytest.mark.asyncio
async def test_list_by_connection() -> None:
    now = datetime.now(UTC)
    records = [
        ConnectionStreamStateRecord(
            id=f"ip_cst_{i}",
            tenant_id="t1",
            connection_id="c1",
            stream_name=f"stream_{i}",
            cursor_field="seq",
            cursor_value=str(i),
            records_synced_count=i,
            last_synced_at=now,
        )
        for i in range(3)
    ]
    session = FakeAsyncSession(query_result=records)
    repo = SqlAlchemyStreamStateRepository(cast(AsyncSession, session))

    result = await repo.list_by_connection("t1", "c1")
    assert len(result) == 3
    assert result[0].stream_name == "stream_0"
    assert result[2].records_synced_count == 2


@pytest.mark.asyncio
async def test_save_new_state() -> None:
    session = FakeAsyncSession(query_result=None)
    repo = SqlAlchemyStreamStateRepository(cast(AsyncSession, session))

    new_state = ConnectionStreamState(
        id="ip_cst_new",
        tenant_id="t1",
        connection_id="c1",
        stream_name="customers",
        cursor_field="updated_at",
        cursor_value="2026-10-20",
        records_synced_count=10,
        last_synced_at=datetime.now(UTC),
    )

    await repo.save(new_state)
    assert len(session.added_records) == 1
    added = session.added_records[0]
    assert added.id == "ip_cst_new"
    assert added.stream_name == "customers"
    assert session.flushed is True


@pytest.mark.asyncio
async def test_save_existing_state() -> None:
    existing_record = ConnectionStreamStateRecord(
        id="ip_cst_existing",
        tenant_id="t1",
        connection_id="c1",
        stream_name="customers",
        cursor_field="updated_at",
        cursor_value="2026-10-19",
        records_synced_count=5,
        last_synced_at=datetime.now(UTC),
    )
    session = FakeAsyncSession(query_result=existing_record)
    repo = SqlAlchemyStreamStateRepository(cast(AsyncSession, session))

    updated_state = ConnectionStreamState(
        id="ip_cst_existing",
        tenant_id="t1",
        connection_id="c1",
        stream_name="customers",
        cursor_field="updated_at",
        cursor_value="2026-10-20",
        records_synced_count=15,
        last_synced_at=datetime.now(UTC),
    )

    await repo.save(updated_state)
    assert len(session.added_records) == 0  # Should NOT add duplicate
    assert existing_record.cursor_value == "2026-10-20"
    assert existing_record.records_synced_count == 15
    assert session.flushed is True


@pytest.mark.asyncio
async def test_save_drains_domain_events_to_outbox() -> None:
    session = FakeAsyncSession(query_result=None)
    repo = SqlAlchemyStreamStateRepository(cast(AsyncSession, session))

    state = ConnectionStreamState.create(
        tenant_id="tenant_123",
        connection_id="conn_456",
        stream_name="invoices",
        cursor_field="id",
        initial_cursor="0",
    )
    state.advance_checkpoint(new_cursor_value="100", records_in_batch=50)
    assert len(state.domain_events) == 1

    await repo.save(state)

    # Verify domain events were drained and cleared from aggregate
    assert len(state.domain_events) == 0

    # Verify session received the state record AND the outbox record
    assert len(session.added_records) == 2
    state_rec = next(r for r in session.added_records if isinstance(r, ConnectionStreamStateRecord))
    outbox_rec = next(r for r in session.added_records if isinstance(r, IpOutboxRecord))

    assert state_rec.id == state.id
    assert outbox_rec.event_type == "ip.stream_state.checkpointed"
    assert outbox_rec.tenant_id == "tenant_123"
    assert outbox_rec.payload["cursor_value"] == "100"
    assert outbox_rec.payload["records_synced_count"] == 50
    assert session.flushed is True
