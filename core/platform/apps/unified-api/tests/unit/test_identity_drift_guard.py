"""Narrow integration/unit tests for startup Platform Tenant IdP Org drift diagnostics."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import database.provider
import pytest
import structlog.testing
from database.models.identity import Tenant as TenantORM
from database.provider import DatabaseProvider, get_async_engine
from fastapi import FastAPI
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import Table, insert, text
from sqlalchemy.ext.asyncio import AsyncConnection

from unified_api.bootstrap.identity_drift_guard import verify_platform_tenant_idp_alignment
from unified_api.bootstrap.lifespan import shell_lifespan
from unified_api.settings import get_settings


async def _prepare_sqlite_identity_schema(conn: AsyncConnection) -> None:
    await conn.execute(text("ATTACH DATABASE ':memory:' AS identity"))
    tenant_table = TenantORM.__table__
    assert isinstance(tenant_table, Table)
    await conn.run_sync(tenant_table.create)


@pytest.mark.asyncio
async def test_verify_platform_tenant_idp_alignment_quiet_when_aligned() -> None:
    engine = get_async_engine("sqlite+aiosqlite:///:memory:")
    provider = DatabaseProvider(engine)
    try:
        async with engine.begin() as conn:
            await _prepare_sqlite_identity_schema(conn)
            await conn.execute(
                insert(TenantORM).values(
                    id=PLATFORM_TENANT_ID,
                    name="Platform Organization",
                    slug="platform",
                    idp_tenant_id="397365687661625347",
                    status="active",
                )
            )

        with structlog.testing.capture_logs() as captured:
            aligned = await verify_platform_tenant_idp_alignment(
                db_provider=provider,
                expected_platform_org_id="397365687661625347",
            )

        assert aligned is True
        error_events = [entry for entry in captured if entry.get("log_level") == "error"]
        assert error_events == []
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_verify_platform_tenant_idp_alignment_logs_error_on_mismatch() -> None:
    engine = get_async_engine("sqlite+aiosqlite:///:memory:")
    provider = DatabaseProvider(engine)
    try:
        async with engine.begin() as conn:
            await _prepare_sqlite_identity_schema(conn)
            await conn.execute(
                insert(TenantORM).values(
                    id=PLATFORM_TENANT_ID,
                    name="Platform Organization",
                    slug="platform",
                    idp_tenant_id="384772010141548547",
                    status="active",
                )
            )

        with structlog.testing.capture_logs() as captured:
            aligned = await verify_platform_tenant_idp_alignment(
                db_provider=provider,
                expected_platform_org_id="397365687661625347",
            )

        assert aligned is False
        mismatch_logs = [
            entry for entry in captured if entry.get("event") == "local_identity_org_id_mismatch"
        ]
        assert len(mismatch_logs) == 1
        entry = mismatch_logs[0]
        assert entry["log_level"] == "error"
        assert entry["env_org_id"] == "397365687661625347"
        assert entry["db_org_id"] == "384772010141548547"
        assert "pnpm db:seed" in str(entry["remedy"])
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_verify_platform_tenant_idp_alignment_logs_error_when_tenant_missing() -> None:
    engine = get_async_engine("sqlite+aiosqlite:///:memory:")
    provider = DatabaseProvider(engine)
    try:
        async with engine.begin() as conn:
            await _prepare_sqlite_identity_schema(conn)

        with structlog.testing.capture_logs() as captured:
            aligned = await verify_platform_tenant_idp_alignment(
                db_provider=provider,
                expected_platform_org_id="397365687661625347",
            )

        assert aligned is False
        missing_logs = [
            entry
            for entry in captured
            if entry.get("event") == "local_identity_platform_tenant_missing"
        ]
        assert len(missing_logs) == 1
        assert missing_logs[0]["log_level"] == "error"
        assert "pnpm db:seed" in str(missing_logs[0]["remedy"])
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_verify_platform_tenant_idp_alignment_logs_and_returns_false_on_driver_error() -> (
    None
):
    provider = DatabaseProvider.from_url(
        "postgresql+asyncpg://postgres:password@127.0.0.1:1/unreachable_test"
    )
    try:
        with structlog.testing.capture_logs() as captured:
            aligned = await verify_platform_tenant_idp_alignment(
                db_provider=provider,
                expected_platform_org_id="397365687661625347",
            )

        assert aligned is False
        failure_logs = [
            entry
            for entry in captured
            if entry.get("event") == "platform_tenant_idp_alignment_check_failed"
        ]
        assert len(failure_logs) == 1
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_verify_platform_tenant_idp_alignment_logs_distinct_error_when_org_unset() -> None:
    engine = get_async_engine("sqlite+aiosqlite:///:memory:")
    provider = DatabaseProvider(engine)
    try:
        async with engine.begin() as conn:
            await _prepare_sqlite_identity_schema(conn)
            await conn.execute(
                insert(TenantORM).values(
                    id=PLATFORM_TENANT_ID,
                    name="Platform Organization",
                    slug="platform",
                    idp_tenant_id=None,
                    status="active",
                )
            )

        with structlog.testing.capture_logs() as captured:
            aligned = await verify_platform_tenant_idp_alignment(
                db_provider=provider,
                expected_platform_org_id="397365687661625347",
            )

        assert aligned is False
        unset_logs = [
            entry for entry in captured if entry.get("event") == "local_identity_platform_org_unset"
        ]
        missing_logs = [
            entry
            for entry in captured
            if entry.get("event") == "local_identity_platform_tenant_missing"
        ]
        assert len(unset_logs) == 1
        assert missing_logs == []
        assert unset_logs[0]["log_level"] == "error"
        assert "pnpm db:seed" in str(unset_logs[0]["remedy"])
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_verify_platform_tenant_idp_alignment_ignores_soft_deleted_platform_tenant() -> None:
    engine = get_async_engine("sqlite+aiosqlite:///:memory:")
    provider = DatabaseProvider(engine)
    try:
        async with engine.begin() as conn:
            await _prepare_sqlite_identity_schema(conn)
            await conn.execute(
                insert(TenantORM).values(
                    id=PLATFORM_TENANT_ID,
                    name="Platform Organization",
                    slug="platform",
                    idp_tenant_id="397365687661625347",
                    status="inactive",
                    deleted_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )

        with structlog.testing.capture_logs() as captured:
            aligned = await verify_platform_tenant_idp_alignment(
                db_provider=provider,
                expected_platform_org_id="397365687661625347",
            )

        assert aligned is False
        missing_logs = [
            entry
            for entry in captured
            if entry.get("event") == "local_identity_platform_tenant_missing"
        ]
        assert len(missing_logs) == 1
    finally:
        await provider.close()


class _RaisingSessionProvider:
    def __init__(self) -> None:
        self.closed = False

    @contextlib.asynccontextmanager
    async def session(self) -> AsyncIterator[None]:
        raise RuntimeError("unexpected non-driver failure during drift guard")
        yield

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_shell_lifespan_closes_db_provider_when_drift_check_raises_unexpected_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _RaisingSessionProvider()
    monkeypatch.setattr(
        database.provider.DatabaseProvider,
        "from_url",
        classmethod(lambda cls, url, **kwargs: provider),
    )

    test_app = FastAPI()
    test_app.state.settings = get_settings()
    test_app.state.ucp_container = None
    test_app.state.api_modules = []

    with pytest.raises(RuntimeError, match="unexpected non-driver failure during drift guard"):
        async with shell_lifespan(test_app):
            pass

    assert provider.closed is True


@pytest.mark.asyncio
async def test_shell_lifespan_passes_resolved_database_url_to_both_provider_and_router(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_url = "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/override_db_test"
    captured_urls: dict[str, str] = {}

    class _NoOpProvider:
        def __init__(self) -> None:
            self.closed = False

        @contextlib.asynccontextmanager
        async def session(self) -> AsyncIterator[None]:
            yield

        async def close(self) -> None:
            self.closed = True

    class _CapturingRouter:
        def __init__(self, *, global_db_url: str, **kwargs: object) -> None:
            _ = kwargs
            captured_urls["router_url"] = global_db_url

        async def close_all(self) -> None:
            pass

    provider = _NoOpProvider()
    monkeypatch.setenv("DATABASE_URL", override_url)
    monkeypatch.setattr(
        database.provider.DatabaseProvider,
        "from_url",
        classmethod(
            lambda cls, url, **kwargs: (captured_urls.setdefault("provider_url", url), provider)[1]
        ),
    )
    monkeypatch.setattr("unified_api.bootstrap.lifespan.DatabaseRouter", _CapturingRouter)
    monkeypatch.setattr(
        "unified_api.bootstrap.lifespan.verify_platform_tenant_idp_alignment",
        lambda **kwargs: _async_true(),
    )
    monkeypatch.setattr("unified_api.bootstrap.lifespan.ucp_startup", _async_noop)
    monkeypatch.setattr("unified_api.bootstrap.lifespan.ucp_shutdown", _async_noop)
    monkeypatch.setattr("unified_api.bootstrap.lifespan.notification_startup", _async_noop)
    monkeypatch.setattr("unified_api.bootstrap.lifespan.notification_shutdown", _async_noop)

    test_app = FastAPI()
    test_app.state.settings = get_settings()
    test_app.state.ucp_container = None
    test_app.state.api_modules = []

    async with shell_lifespan(test_app):
        pass

    assert captured_urls["provider_url"] == override_url
    assert captured_urls["router_url"] == override_url


async def _async_true() -> bool:
    return True


async def _async_noop() -> None:
    return None
