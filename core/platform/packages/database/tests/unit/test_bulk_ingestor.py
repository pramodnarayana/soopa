from __future__ import annotations

from typing import cast

import pytest

from database.bulk_ingestor import SqlAlchemyBulkRecordIngestor
from database.types import TenantSession


class _FakeDriverConn:
    def __init__(self) -> None:
        self.copied_batches: list[tuple[str, str, list[str], int]] = []

    async def copy_records_to_table(
        self,
        table_name: str,
        *,
        records: object,
        columns: list[str],
        schema_name: str,
    ) -> None:
        rows = list(records) if isinstance(records, (list, tuple)) else []
        self.copied_batches.append((schema_name, table_name, columns, len(rows)))


class _FakeRawConn:
    def __init__(self, driver_connection: _FakeDriverConn | None) -> None:
        self.driver_connection = driver_connection


class _FakeSaConn:
    def __init__(self, raw_conn: _FakeRawConn) -> None:
        self._raw = raw_conn

    async def get_raw_connection(self) -> _FakeRawConn:
        return self._raw


class _FakeTenantSession:
    def __init__(self, driver_connection: _FakeDriverConn | None) -> None:
        self.executed: list[tuple[str, object]] = []
        self._sa_conn = _FakeSaConn(_FakeRawConn(driver_connection))

    async def execute(self, stmt: object, params: object = None) -> None:
        self.executed.append((str(stmt), params))

    async def connection(self) -> _FakeSaConn:
        return self._sa_conn


@pytest.mark.asyncio
async def test_bulk_ingestor_sets_rls_context_before_driver_copy() -> None:
    driver = _FakeDriverConn()
    raw_session = _FakeTenantSession(driver)
    fake_session = cast(TenantSession, raw_session)
    ingestor = SqlAlchemyBulkRecordIngestor(session=fake_session)

    inserted = await ingestor.ingest_batch(
        tenant_id="iam_ten_alpha01",
        table_name="stream_events",
        columns=["id", "tenant_id", "value"],
        records=[
            ("evt_1", "iam_ten_alpha01", 10),
            ("evt_2", "iam_ten_alpha01", 20),
        ],
        schema_name="public",
    )
    assert inserted == 2
    assert "platform.current_tenant_id" in raw_session.executed[0][0]
    assert driver.copied_batches == [("public", "stream_events", ["id", "tenant_id", "value"], 2)]


@pytest.mark.asyncio
async def test_bulk_ingestor_handles_empty_records_and_validates_inputs() -> None:
    driver = _FakeDriverConn()
    fake_session = cast(TenantSession, _FakeTenantSession(driver))
    ingestor = SqlAlchemyBulkRecordIngestor(session=fake_session)

    assert (
        await ingestor.ingest_batch(
            tenant_id="iam_ten_alpha01",
            table_name="stream_events",
            columns=["id"],
            records=[],
        )
        == 0
    )

    with pytest.raises(ValueError, match="columns must be non-empty"):
        await ingestor.ingest_batch(
            tenant_id="iam_ten_alpha01",
            table_name="stream_events",
            columns=[],
            records=[("evt_1",)],
        )

    missing_driver_session = cast(TenantSession, _FakeTenantSession(None))
    broken_ingestor = SqlAlchemyBulkRecordIngestor(session=missing_driver_session)
    with pytest.raises(RuntimeError, match="driver connection is unavailable"):
        await broken_ingestor.ingest_batch(
            tenant_id="iam_ten_alpha01",
            table_name="stream_events",
            columns=["id"],
            records=[("evt_1",)],
        )
