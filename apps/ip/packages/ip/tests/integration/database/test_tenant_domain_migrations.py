"""Narrow integration tests verifying domain migrations, ownership, isolation, and RLS policies."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from ip.application.domains.registry import (
    DOMAIN_MIGRATION_MODULES,
)
from ip.engine.adapters.outbound.database.models.base import IpTenantBase
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine


def test_domain_migration_modules_ownership_and_invariants() -> None:
    """Verifies that every table in IpTenantBase.metadata is owned by exactly one domain branch."""
    all_metadata_tables = set(IpTenantBase.registry.metadata.tables.keys())
    assert len(all_metadata_tables) == 12

    branch_labels: set[str] = set()
    claimed_tables: set[str] = set()

    for module in DOMAIN_MIGRATION_MODULES:
        assert module.branch_label not in branch_labels, (
            f"Duplicate branch label: {module.branch_label}"
        )
        branch_labels.add(module.branch_label)

        for table in module.owned_tables:
            assert table in all_metadata_tables, (
                f"Table {table} owned by {module.branch_label} not in metadata"
            )
            assert table not in claimed_tables, f"Table {table} claimed by multiple branches"
            claimed_tables.add(table)

    assert claimed_tables == all_metadata_tables, (
        f"Missing table ownership: {all_metadata_tables - claimed_tables}"
    )


@pytest.mark.asyncio
async def test_tenant_domain_migrations_rls_and_isolation(
    tenant_db_connection: AsyncConnection,
) -> None:
    """Verifies that RLS and tenant_isolation policies are active on all tenant tables."""
    all_tables = [table for m in DOMAIN_MIGRATION_MODULES for table in m.owned_tables]

    # Check pg_class relrowsecurity
    rel_res = await tenant_db_connection.execute(
        text("SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY(:names)"),
        {"names": all_tables},
    )
    rls_map = {row[0]: row[1] for row in rel_res.fetchall()}
    for table in all_tables:
        assert rls_map.get(table) is True, f"RLS not enabled on table {table}"

    # Check pg_policies
    pol_res = await tenant_db_connection.execute(
        text("SELECT tablename, policyname FROM pg_policies WHERE tablename = ANY(:names)"),
        {"names": all_tables},
    )
    policy_map = {row[0]: row[1] for row in pol_res.fetchall()}
    for table in all_tables:
        expected_policy = f"tenant_isolation_{table}"
        assert policy_map.get(table) == expected_policy, (
            f"Policy {expected_policy} missing on {table}"
        )


@pytest.mark.asyncio
async def test_tenant_domain_migrations_downgrade_isolation(
    tenant_db_engine: AsyncEngine,
) -> None:
    """Verifies that downgrading energy@base drops only energy tables while engine and tms stay intact."""
    ini_path = Path(__file__).parents[3] / "alembic.tenant.ini"
    assert ini_path.exists()

    cfg = Config(str(ini_path))
    db_url = (
        os.environ.get("IP_DATABASE_URL")
        or os.environ.get("SHARD_OVERRIDES__IP_SHARD_1")
        or "postgresql+asyncpg://ip:ip_password@localhost:5434/ip_shard"
    )
    sync_url = db_url.replace("+asyncpg", "").replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", sync_url)

    # First upgrade all heads to ensure pristine starting state
    await asyncio.to_thread(command.upgrade, cfg, "heads")

    # Downgrade energy branch only: energy@base
    await asyncio.to_thread(command.downgrade, cfg, "energy@base")

    async with tenant_db_engine.connect() as conn:
        res = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        existing_tables = {row[0] for row in res.fetchall()}

        # Energy tables must be dropped
        assert "mdm_meter_readings" not in existing_tables
        assert "mdm_service_points" not in existing_tables

        # Engine tables must remain intact
        assert "inbound_records" in existing_tables
        assert "replica_records" in existing_tables
        assert "normalized_records" in existing_tables
        assert "global_entity_map" in existing_tables
        assert "outbound_records" in existing_tables

        # TMS tables must remain intact
        assert "tms_loads" in existing_tables
        assert "tms_carriers" in existing_tables

    # Re-upgrade heads so test database is restored
    await asyncio.to_thread(command.upgrade, cfg, "heads")

    async with tenant_db_engine.connect() as conn:
        res = await conn.execute(
            text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        )
        restored_tables = {row[0] for row in res.fetchall()}
        assert "mdm_meter_readings" in restored_tables
        assert "mdm_service_points" in restored_tables
