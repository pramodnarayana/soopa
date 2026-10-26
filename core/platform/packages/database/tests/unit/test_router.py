from collections.abc import AsyncGenerator
from typing import Any, cast

import pytest

from database.router import DatabaseRouter
from database.types import GlobalSession


def test_resolve_dsn_applies_overrides() -> None:
    """Test that DatabaseRouter properly resolves DSN overrides regardless of case."""
    # 1. Arrange: Simulate Pydantic injecting environment variables
    # Pydantic often converts config values in unexpected ways depending on case sensitivity configs.
    # We'll simulate a mix of lowercase, uppercase, and mixed-case keys.
    overrides = {
        "EDI_SHARD_1": "postgresql+asyncpg://edi@localhost/override_1",
        "edi_shard_2": "postgresql+asyncpg://edi@localhost/override_2",
        "Edi_Shard_3": "postgresql+asyncpg://edi@localhost/override_3",
    }
    router = DatabaseRouter(
        global_db_url="postgresql+asyncpg://global@localhost/global",
        shard_overrides=overrides,
    )

    # 2. Act & Assert: Verify it resolves correctly against exactly matching keys,
    # completely different casing, and missing keys.

    # 2.1 Exact Match (but original was uppercase)
    assert (
        router._resolve_dsn("default_dsn", "EDI_SHARD_1")
        == "postgresql+asyncpg://edi@localhost/override_1"
    )

    # 2.2 Lowercase query for an uppercase original key
    assert (
        router._resolve_dsn("default_dsn", "edi_shard_1")
        == "postgresql+asyncpg://edi@localhost/override_1"
    )

    # 2.3 Uppercase query for a lowercase original key
    assert (
        router._resolve_dsn("default_dsn", "EDI_SHARD_2")
        == "postgresql+asyncpg://edi@localhost/override_2"
    )

    # 2.4 Mixed case query for a mixed case original key
    assert (
        router._resolve_dsn("default_dsn", "eDi_ShArD_3")
        == "postgresql+asyncpg://edi@localhost/override_3"
    )

    # 2.5 Fallback test (multiple keys)
    assert (
        router._resolve_dsn("default_dsn", "non_existent", "EDI_SHARD_1")
        == "postgresql+asyncpg://edi@localhost/override_1"
    )

    # 2.6 Missing key completely returns the default DSN
    assert router._resolve_dsn("default_dsn", "MISSING_SHARD") == "default_dsn"


class _DummyShardRow:
    def __init__(self, id: str, name: str, dsn: str) -> None:
        self.id = id
        self.name = name
        self.dsn = dsn


class _FakeSession:
    def __init__(self, rows: list[_DummyShardRow]) -> None:
        self.rows = rows
        self.executed_stmts: list[object] = []

    async def execute(self, stmt: object) -> list[_DummyShardRow]:
        self.executed_stmts.append(stmt)
        return self.rows


class _TestDatabaseRouter(DatabaseRouter):
    def __init__(self, fake_session: _FakeSession, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._fake_session = fake_session

    async def get_global_session(self) -> AsyncGenerator[GlobalSession, None]:
        yield cast(GlobalSession, self._fake_session)


@pytest.mark.asyncio
async def test_get_all_shards_with_app_slug() -> None:
    fake_session = _FakeSession(
        [_DummyShardRow("edi_shard_1", "EDI Shard", "postgresql+asyncpg://orig/dsn")]
    )
    router = _TestDatabaseRouter(
        fake_session=fake_session,
        global_db_url="postgresql+asyncpg://global@localhost/global",
        shard_overrides={"edi_shard_1": "postgresql+asyncpg://override/dsn"},
    )

    shards = await router.get_all_shards(app_slug="edi")
    assert len(shards) == 1
    assert shards[0] == ("edi_shard_1", "postgresql+asyncpg://override/dsn")
    assert len(fake_session.executed_stmts) == 1
    stmt_str = str(fake_session.executed_stmts[0])
    assert "apps.slug = :slug_1" in stmt_str or "database_shards.id" in stmt_str


@pytest.mark.asyncio
async def test_get_all_shards_without_app_slug() -> None:
    fake_session = _FakeSession(
        [
            _DummyShardRow("edi_shard_1", "EDI Shard", "postgresql+asyncpg://orig/dsn1"),
            _DummyShardRow("ip_shard_1", "IP Shard", "postgresql+asyncpg://orig/dsn2"),
        ]
    )
    router = _TestDatabaseRouter(
        fake_session=fake_session,
        global_db_url="postgresql+asyncpg://global@localhost/global",
    )

    shards = await router.get_all_shards()
    assert len(shards) == 2
    assert shards[0] == ("edi_shard_1", "postgresql+asyncpg://orig/dsn1")
    assert shards[1] == ("ip_shard_1", "postgresql+asyncpg://orig/dsn2")
