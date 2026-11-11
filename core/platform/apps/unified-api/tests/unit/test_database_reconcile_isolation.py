"""Unit tests for test database DSN hydration, IP multi-shard discovery, and reconcile domain guards."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import pytest
from database.shard_discovery import collect_prefixed_shard_overrides
from ensure_test_databases import (
    discover_test_database_targets,
    hydrate_database_env_from_selected_file,
)
from reconcile_schema_drift import (
    RECONCILABLE_APP_DOMAINS,
    _load_database_settings,
    _parse_cli_args,
    reconcile,
    resolve_ip_shard_urls,
    validate_reconcile_domain,
)
from seedwork.infra.config import ENV_FILE_SELECTOR_VAR
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy.engine import URL


def _build_pg_dsn(
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
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    async def __aenter__(self) -> _FakeAsyncSession:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def execute(self, _statement: object) -> _FakeShardResult:
        return _FakeShardResult(self._rows)


class _FakeDatabaseProvider:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows
        self.closed = False

    def session(self) -> _FakeAsyncSession:
        return _FakeAsyncSession(self._rows)

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_reconcile_rejects_unsupported_domain_before_database_connection() -> None:
    with pytest.raises(ValueError, match="Unsupported reconciliation domain 'ipp'"):
        await reconcile(domain="ipp", skip_dotenv=True)

    with pytest.raises(ValueError, match="Unsupported reconciliation domain 'edi'"):
        validate_reconcile_domain("edi")

    assert "ip" in RECONCILABLE_APP_DOMAINS
    assert "edi" not in RECONCILABLE_APP_DOMAINS


def test_reconcile_cli_rejects_unknown_domain_argument() -> None:
    with pytest.raises(SystemExit):
        _parse_cli_args(["--domain", "ipp"])

    parsed = _parse_cli_args(["--domain", "IP", "--skip-dotenv"])
    assert parsed.domain == "ip"
    assert parsed.skip_dotenv is True


def test_hydrate_database_env_resolves_selected_env_file_before_target_discovery(
    tmp_path: Path,
) -> None:
    global_live = _build_pg_dsn(
        drivername="postgresql",
        username="ucp_admin",
        db_cred="ucp_password",
        host="localhost",
        port=5432,
        database="global_db",
    )
    ip_live = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="ip_password",
        host="localhost",
        port=5434,
        database="ip_shard",
    )
    selected_env = tmp_path / ".env.custom"
    selected_env.write_text(
        "\n".join(
            [
                f"DATABASE_URL={global_live}",
                f"IP_DATABASE_URL={ip_live}",
                f"SHARD_OVERRIDES__IP_SHARD_1={ip_live}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    caller_env = {
        ENV_FILE_SELECTOR_VAR: str(selected_env),
    }
    hydrated = hydrate_database_env_from_selected_file(tmp_path, caller_env)

    expected_global_test = _build_pg_dsn(
        drivername="postgresql",
        username="ucp_admin",
        db_cred="ucp_password",
        host="localhost",
        port=5432,
        database="global_db_test",
    )
    expected_ip_test = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="ip_password",
        host="localhost",
        port=5434,
        database="ip_shard_test",
    )
    assert hydrated["DATABASE_URL"] == expected_global_test
    assert hydrated["IP_DATABASE_URL"] == expected_ip_test
    assert hydrated["SHARD_OVERRIDES__IP_SHARD_1"] == expected_ip_test
    assert hydrated["DATABASE__SHARD_OVERRIDES__IP_SHARD_1"] == expected_ip_test

    targets = discover_test_database_targets(hydrated)
    assert [t.db_name for t in targets] == ["global_db_test", "ip_shard_test"]


def test_skip_dotenv_prevents_reconcile_from_loading_unrewritten_url_from_disk(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_live = _build_pg_dsn(
        drivername="postgresql",
        username="ucp_admin",
        db_cred="ucp_password",
        host="localhost",
        port=5432,
        database="global_db",
    )
    ip_live = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="ip_password",
        host="localhost",
        port=5434,
        database="ip_shard",
    )
    global_test = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ucp_admin",
        db_cred="ucp_password",
        host="localhost",
        port=5432,
        database="global_db_test",
    )
    live_env = tmp_path / ".env"
    live_env.write_text(
        f"DATABASE_URL={global_live}\nIP_DATABASE_URL={ip_live}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_FILE_SELECTOR_VAR, str(live_env))
    monkeypatch.setenv("DATABASE_URL", global_test)
    monkeypatch.delenv("IP_DATABASE_URL", raising=False)

    settings = _load_database_settings(skip_dotenv=True)
    assert settings.global_url.endswith("/global_db_test")
    assert "IP_DATABASE_URL" not in os.environ


@pytest.mark.asyncio
async def test_resolve_ip_shard_urls_discovers_all_distinct_shards_with_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shard_1_docker = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="ip_postgres_shard",
        port=5432,
        database="ip_shard",
    )
    shard_2_sync = _build_pg_dsn(
        drivername="postgresql",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5435,
        database="ip_shard_2",
    )
    edi_shard = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="edi",
        db_cred="pw",
        host="localhost",
        port=5433,
        database="edi_shard",
    )
    fake_provider = _FakeDatabaseProvider(
        rows=[
            ("ip_shard_1", shard_1_docker),
            ("ip_shard_2", shard_2_sync),
            ("edi_shard_1", edi_shard),
        ]
    )
    monkeypatch.setattr(
        "database.shard_discovery.DatabaseProvider.from_url",
        lambda _url: fake_provider,
    )

    global_test = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ucp_admin",
        db_cred="pw",
        host="localhost",
        port=5432,
        database="global_db_test",
    )
    from_settings = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="from_settings",
    )
    from_ip_db_url = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="from_ip_db_url",
    )
    ip_shard_test = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5434,
        database="ip_shard_test",
    )
    ip_shard_2_async = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5435,
        database="ip_shard_2",
    )
    ip_shard_3_test = _build_pg_dsn(
        drivername="postgresql+asyncpg",
        username="ip",
        db_cred="pw",
        host="localhost",
        port=5436,
        database="ip_shard_3_test",
    )

    settings = PlatformDatabaseSettings(
        DATABASE_URL=global_test,
        shard_overrides={"ip_shard_1": from_settings},
    )
    environ = {
        "IP_DATABASE_URL": from_ip_db_url,
        "SHARD_OVERRIDES__IP_SHARD_1": ip_shard_test,
        "SHARD_OVERRIDES__IP_SHARD_3": ip_shard_3_test,
    }

    overrides = collect_prefixed_shard_overrides(
        environ,
        settings.shard_overrides,
        shard_prefix="ip_",
        default_shard_id="ip_shard_1",
        default_dsn_env_var="IP_DATABASE_URL",
    )
    assert overrides["ip_shard_1"] == ip_shard_test

    urls = await resolve_ip_shard_urls(settings.global_url, settings, environ)
    assert urls == [
        ip_shard_test,
        ip_shard_2_async,
        ip_shard_3_test,
    ]
    assert fake_provider.closed is True
