"""Unit tests for PostgreSQL test database DSN rewriting and fail-closed test guards."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from database.pytest_plugin import _env_isolated_load_dotenv, install_pytest_database_guard
from database.testing import assert_test_database_url
from database.utils import (
    build_maintenance_dsn,
    extract_database_name,
    rewrite_dsn_to_test_db,
)


def test_extract_database_name_parses_sync_and_async_dsns() -> None:
    assert (
        extract_database_name("postgresql://ucp_admin:ucp_password@localhost:5432/global_db")
        == "global_db"
    )
    assert (
        extract_database_name("postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard")
        == "edi_shard"
    )
    assert extract_database_name("") == ""


def test_rewrite_dsn_to_test_db_is_idempotent_and_preserves_driver_and_query() -> None:
    assert (
        rewrite_dsn_to_test_db("postgresql://ucp_admin:ucp_password@localhost:5432/global_db")
        == "postgresql://ucp_admin:ucp_password@localhost:5432/global_db_test"
    )
    assert (
        rewrite_dsn_to_test_db(
            "postgresql+asyncpg://edi:p%40ss@localhost:5433/edi_shard?ssl=disable"
        )
        == "postgresql+asyncpg://edi:p%40ss@localhost:5433/edi_shard_test?ssl=disable"
    )
    # Idempotent when already targeting *_test
    already_test = "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/global_db_test"
    assert rewrite_dsn_to_test_db(already_test) == already_test

    # Leaves sqlite URLs untouched
    sqlite_url = "sqlite+aiosqlite:///:memory:"
    assert rewrite_dsn_to_test_db(sqlite_url) == sqlite_url


@pytest.mark.parametrize(
    "missing_db_dsn",
    [
        "postgresql://ucp_admin:ucp_password@localhost:5432/",
        "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432",
        "postgresql+psycopg2://ucp_admin:ucp_password@localhost:5432/",
    ],
)
def test_rewrite_dsn_to_test_db_rejects_postgres_dsn_without_database_name(
    missing_db_dsn: str,
) -> None:
    with pytest.raises(ValueError, match="missing a database name") as exc_info:
        rewrite_dsn_to_test_db(missing_db_dsn)
    assert "ucp_password" not in str(exc_info.value)


def test_build_maintenance_dsn_switches_to_postgres_and_standard_driver() -> None:
    assert (
        build_maintenance_dsn(
            "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/global_db_test"
        )
        == "postgresql://ucp_admin:ucp_password@localhost:5432/postgres"
    )


def test_assert_test_database_url_allows_isolated_test_databases_and_sqlite() -> None:
    global_test = "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/global_db_test"
    shard_test = "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_test"
    sqlite_mem = "sqlite+aiosqlite:///:memory:"

    assert assert_test_database_url(global_test) == global_test
    assert assert_test_database_url(shard_test) == shard_test
    assert assert_test_database_url(sqlite_mem) == sqlite_mem


@pytest.mark.parametrize(
    "unsafe_dsn",
    [
        "postgresql://ucp_admin:ucp_password@localhost:5432/global_db",
        "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard",
        "postgresql+asyncpg://billing:billing_password@localhost:5434/billing_shard",
        "postgresql://ucp_admin:ucp_password@localhost:5432/soopa_global",
        "mysql://root:secret_pw@localhost:3306/app_test",
        "://malformed:secret_pw@localhost/global_db_test",
        "",
    ],
)
def test_assert_test_database_url_rejects_live_development_databases(
    unsafe_dsn: str,
) -> None:
    with pytest.raises(RuntimeError) as exc_info:
        assert_test_database_url(unsafe_dsn)
    assert "secret_pw" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_pytest_plugin_blocks_async_connection_to_live_postgres_before_socket() -> None:
    install_pytest_database_guard()
    engine = create_async_engine(
        "postgresql+asyncpg://ucp_admin:ucp_password@127.0.0.1:1/global_db"
    )
    try:
        with pytest.raises(RuntimeError, match="non-test PostgreSQL database 'global_db'"):
            async with engine.connect():
                pass
    finally:
        await engine.dispose()


def test_pytest_plugin_redirects_bare_load_dotenv_to_soopa_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    isolated_env = tmp_path / ".env.example"
    isolated_env.write_text("SOOPA_TEST_PLUGIN_TOKEN=from_example\n", encoding="utf-8")
    monkeypatch.setenv("SOOPA_ENV_FILE", str(isolated_env))
    monkeypatch.delenv("SOOPA_TEST_PLUGIN_TOKEN", raising=False)

    loaded = _env_isolated_load_dotenv()

    assert loaded is True
    assert os.environ.get("SOOPA_TEST_PLUGIN_TOKEN") == "from_example"
