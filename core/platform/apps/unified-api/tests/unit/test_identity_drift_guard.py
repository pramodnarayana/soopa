"""Narrow integration/unit tests for startup Platform Tenant IdP Org drift diagnostics."""

from __future__ import annotations

import pytest
import structlog.testing
from database.models.identity import Tenant as TenantORM
from database.provider import DatabaseProvider, get_async_engine
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import Table, insert, text
from sqlalchemy.ext.asyncio import AsyncConnection

from unified_api.bootstrap.identity_drift_guard import verify_platform_tenant_idp_alignment


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
