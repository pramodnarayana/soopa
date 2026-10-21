"""Unit tests for SqlAlchemyConnectionRepository."""

from __future__ import annotations

from typing import Any, cast

import pytest
from ip.adapters.outbound.database.connection_repository import SqlAlchemyConnectionRepository
from ip.adapters.outbound.database.models.connection_model import ConnectionRecord
from ip.adapters.outbound.database.models.outbox_model import IpOutboxRecord
from ip.domain.exceptions import DuplicateConnectionFingerprintException
from ip.domain.models.connection import AuthType, Connection
from sqlalchemy.exc import IntegrityError
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
    def __init__(self, query_result: Any = None, should_fail_integrity: str | None = None) -> None:
        self.query_result = query_result
        self.should_fail_integrity = should_fail_integrity
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
        if self.should_fail_integrity:
            orig = Exception(self.should_fail_integrity)
            raise IntegrityError("statement", {}, orig)


@pytest.mark.asyncio
async def test_save_new_connection_creates_record_and_outbox() -> None:
    session = FakeAsyncSession(query_result=None)
    repo = SqlAlchemyConnectionRepository(cast(AsyncSession, session))

    connection = Connection.create(
        tenant_id="ten_1",
        app_id="itron_mdm",
        name="Production Itron",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.example.com"},
        encrypted_credentials=b"encrypted",
        endpoint_for_fingerprint="https://api.example.com",
    )

    await repo.save(connection)

    assert session.flushed is True
    # 1 ConnectionRecord + 1 IpOutboxRecord for ConnectionCreatedEvent
    assert len(session.added_records) == 2
    record = next(r for r in session.added_records if isinstance(r, ConnectionRecord))
    outbox = next(r for r in session.added_records if isinstance(r, IpOutboxRecord))

    assert record.id == connection.id
    assert record.tenant_id == "ten_1"
    assert record.connection_fingerprint == connection.connection_fingerprint
    assert outbox.event_type == "ip.connection.created"


@pytest.mark.asyncio
async def test_save_translates_unique_fingerprint_integrity_error() -> None:
    session = FakeAsyncSession(
        query_result=None,
        should_fail_integrity="duplicate key value violates unique constraint 'uq_tenant_active_fingerprint'",
    )
    repo = SqlAlchemyConnectionRepository(cast(AsyncSession, session))

    connection = Connection.create(
        tenant_id="ten_1",
        app_id="itron_mdm",
        name="Duplicate Itron",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.example.com"},
        encrypted_credentials=b"encrypted",
        endpoint_for_fingerprint="https://api.example.com",
    )

    with pytest.raises(
        DuplicateConnectionFingerprintException, match="already exists with fingerprint"
    ):
        await repo.save(connection)


@pytest.mark.asyncio
async def test_save_reraises_other_integrity_errors() -> None:
    session = FakeAsyncSession(
        query_result=None,
        should_fail_integrity="violates foreign key constraint 'fk_tenant_id'",
    )
    repo = SqlAlchemyConnectionRepository(cast(AsyncSession, session))

    connection = Connection.create(
        tenant_id="ten_1",
        app_id="itron_mdm",
        name="Failing Connection",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://api.example.com"},
        encrypted_credentials=None,
        endpoint_for_fingerprint="https://api.example.com",
    )

    with pytest.raises(IntegrityError, match="foreign key"):
        await repo.save(connection)
