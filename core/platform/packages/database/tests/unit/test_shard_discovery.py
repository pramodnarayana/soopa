"""Unit tests for centralized database shard discovery and override precedence."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError

from database.shard_discovery import (
    collect_prefixed_shard_overrides,
    fetch_prefixed_shard_urls,
)


def _pg_dsn(
    *,
    drivername: str,
    username: str,
    db_cred: str,
    host: str,
    port: int,
    database: str,
) -> str:
    return URL.create(
        drivername=drivername,
        username=username,
        password=db_cred,
        host=host,
        port=port,
        database=database,
    ).render_as_string(hide_password=False)


@dataclass(frozen=True)
class _FakeShardResult:
    rows: list[tuple[str, str]]

    def fetchall(self) -> list[tuple[str, str]]:
        return self.rows


class _FakeAsyncSession:
    def __init__(
        self,
        rows: list[tuple[str, str]],
        error: DBAPIError | None = None,
    ) -> None:
        self._rows = rows
        self._error = error

    async def __aenter__(self) -> _FakeAsyncSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> _FakeShardResult:
        if self._error is not None:
            raise self._error
        return _FakeShardResult(self._rows)


class _FakeDatabaseProvider:
    def __init__(
        self,
        rows: list[tuple[str, str]],
        error: DBAPIError | None = None,
    ) -> None:
        self._rows = rows
        self._error = error
        self.closed = False

    def session(self) -> _FakeAsyncSession:
        return _FakeAsyncSession(self._rows, error=self._error)

    async def close(self) -> None:
        self.closed = True


def test_collect_prefixed_shard_overrides_applies_deterministic_precedence() -> None:
    base_shard_1 = _pg_dsn(
        drivername="postgresql",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="base_shard_1",
    )
    base_shard_2 = _pg_dsn(
        drivername="postgresql",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5435,
        database="base_shard_2",
    )
    edi_shard = _pg_dsn(
        drivername="postgresql+asyncpg",
        username="edi",
        db_cred="pw",
        host="localhost",
        port=5433,
        database="edi_shard",
    )
    default_env_dsn = _pg_dsn(
        drivername="postgresql",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="default_env_shard",
    )
    flat_override_1 = _pg_dsn(
        drivername="postgresql",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="flat_override_1",
    )
    flat_override_3 = _pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5436,
        database="flat_override_3",
    )
    nested_override_1 = _pg_dsn(
        drivername="postgresql",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="nested_override_1",
    )

    environ = {
        "IP_DATABASE_URL": default_env_dsn,
        "SHARD_OVERRIDES__IP_SHARD_1": flat_override_1,
        "SHARD_OVERRIDES__IP_SHARD_3": flat_override_3,
        "SHARD_OVERRIDES__EDI_SHARD_1": edi_shard,
        "SHARD_OVERRIDES__IP_EMPTY": "   ",
        "DATABASE__SHARD_OVERRIDES__IP_SHARD_1": nested_override_1,
        "DATABASE__SHARD_OVERRIDES__EDI_SHARD_1": edi_shard,
        "DATABASE__SHARD_OVERRIDES__IP_BLANK": "",
    }
    base_overrides = {
        "IP_SHARD_1": base_shard_1,
        "ip_shard_2": base_shard_2,
        "edi_shard_1": edi_shard,
        "ip_blank": "  ",
    }

    resolved = collect_prefixed_shard_overrides(
        environ,
        base_overrides,
        shard_prefix="IP_",
        default_shard_id="ip_shard_1",
        default_dsn_env_var="IP_DATABASE_URL",
    )

    expected_1 = _pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="nested_override_1",
    )
    expected_2 = _pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5435,
        database="base_shard_2",
    )
    assert resolved == {
        "ip_shard_1": expected_1,
        "ip_shard_2": expected_2,
        "ip_shard_3": flat_override_3,
    }


@pytest.mark.asyncio
async def test_fetch_prefixed_shard_urls_merges_and_deduplicates_shards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_dsn = _pg_dsn(
        drivername="postgresql",
        username="ucp_admin",
        db_cred="pw",
        host="localhost",
        port=5432,
        database="global_db_test",
    )
    catalog_shard_1 = _pg_dsn(
        drivername="postgresql",
        username="ip",
        db_cred="pw",
        host="ip_postgres_shard",
        port=5432,
        database="ip_shard",
    )
    catalog_shard_2 = _pg_dsn(
        drivername="postgresql",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5435,
        database="ip_shard_2_test",
    )
    override_shard_1 = _pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5435,
        database="ip_shard_2_test",
    )
    provider = _FakeDatabaseProvider(
        rows=[
            ("ip_shard_1", catalog_shard_1),
            ("ip_shard_2", catalog_shard_2),
            ("edi_shard_1", global_dsn),
        ]
    )
    monkeypatch.setattr(
        "database.shard_discovery.DatabaseProvider.from_url",
        lambda _url: provider,
    )

    urls = await fetch_prefixed_shard_urls(
        global_dsn,
        {"ip_shard_1": override_shard_1, "edi_shard_1": global_dsn},
        shard_prefix="ip_",
    )

    assert urls == [override_shard_1]
    assert provider.closed is True


@pytest.mark.asyncio
async def test_fetch_prefixed_shard_urls_falls_back_to_overrides_on_db_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_dsn = _pg_dsn(
        drivername="postgresql+asyncpg",
        username="ucp_admin",
        db_cred="pw",
        host="localhost",
        port=5432,
        database="global_db_test",
    )
    override_dsn = _pg_dsn(
        drivername="postgresql",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="ip_shard_test",
    )
    expected_async_dsn = _pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="ip_shard_test",
    )
    db_error = DBAPIError("SELECT id, dsn FROM ucp.database_shards", {}, RuntimeError("offline"))
    provider = _FakeDatabaseProvider(rows=[], error=db_error)
    monkeypatch.setattr(
        "database.shard_discovery.DatabaseProvider.from_url",
        lambda _url: provider,
    )

    urls = await fetch_prefixed_shard_urls(
        global_dsn,
        {"ip_shard_1": override_dsn},
        shard_prefix="ip_",
    )

    assert urls == [expected_async_dsn]
    assert provider.closed is True


@pytest.mark.asyncio
async def test_fetch_prefixed_shard_urls_reraises_db_error_without_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_dsn = _pg_dsn(
        drivername="postgresql+asyncpg",
        username="ucp_admin",
        db_cred="pw",
        host="localhost",
        port=5432,
        database="global_db_test",
    )
    db_error = DBAPIError("SELECT id, dsn FROM ucp.database_shards", {}, RuntimeError("offline"))
    provider = _FakeDatabaseProvider(rows=[], error=db_error)
    monkeypatch.setattr(
        "database.shard_discovery.DatabaseProvider.from_url",
        lambda _url: provider,
    )

    with pytest.raises(DBAPIError):
        await fetch_prefixed_shard_urls(
            global_dsn,
            {},
            shard_prefix="ip_",
        )

    assert provider.closed is True
