"""Integration Platform hybrid multi-tenancy database migration runner (Global Control Plane + Tenant Shards)."""

import asyncio
import os
from collections.abc import Mapping
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from seedwork.infra.config import load_repo_env, load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy import text

from database.provider import DatabaseProvider
from database.shard_discovery import (
    collect_prefixed_shard_overrides,
    fetch_prefixed_shard_urls,
)

logger = structlog.get_logger(__name__)

IP_SHARD_PREFIX = "ip_"
IP_DEFAULT_SHARD_ID = "ip_shard_1"
IP_DEFAULT_DSN_ENV_VAR = "IP_DATABASE_URL"
MIGRATION_BACKFILL_BATCH_SIZE = 500
MIGRATION_BACKFILL_YIELD_SECONDS = 0.1


def collect_ip_shard_overrides(
    environ: Mapping[str, str],
    base_overrides: Mapping[str, str],
) -> dict[str, str]:
    """Resolve IP shard DSN overrides from settings and explicit environment variables."""
    return collect_prefixed_shard_overrides(
        environ,
        base_overrides,
        shard_prefix=IP_SHARD_PREFIX,
        default_shard_id=IP_DEFAULT_SHARD_ID,
        default_dsn_env_var=IP_DEFAULT_DSN_ENV_VAR,
    )


async def reconcile_global_alembic_branch_roots(global_url: str) -> None:
    """Reconciles `ip.alembic_version` for multi-branch `depends_on` DAG semantics."""
    provider = DatabaseProvider.from_url(global_url)
    try:
        async with provider.session() as session:
            version_reg = await session.execute(text("SELECT to_regclass('ip.alembic_version')"))
            conn_reg = await session.execute(text("SELECT to_regclass('ip.connections')"))
            if version_reg.scalar() is None or conn_reg.scalar() is None:
                return

            await session.execute(
                text(
                    """
                    INSERT INTO ip.alembic_version (version_num)
                    SELECT '0001_universal_simulator_schema'
                    WHERE EXISTS (
                        SELECT 1 FROM ip.alembic_version
                        WHERE version_num = '0002_universal_simulator_schema'
                    )
                    ON CONFLICT (version_num) DO NOTHING;
                    """
                )
            )
            await session.execute(
                text(
                    """
                    DELETE FROM ip.alembic_version
                    WHERE version_num = '0002_universal_simulator_schema';
                    """
                )
            )
            await session.execute(
                text(
                    """
                    DELETE FROM ip.alembic_version
                    WHERE version_num = '0001_initial_global_schema'
                      AND EXISTS (
                          SELECT 1 FROM ip.alembic_version AS v2
                          WHERE v2.version_num = '0001_universal_simulator_schema'
                      );
                    """
                )
            )
            await session.commit()
    finally:
        await provider.close()


async def reconcile_global_no_auth_connection_constraint(global_url: str) -> None:
    """Backfill legacy NO_AUTH connections in PENDING_AUTH in chunks and ensure check constraint exists.

    Preserves the single-migration-per-branch invariant (`0001_initial_global_schema.py`) while
    making direct invocations of `run_migrations` safe on databases already stamped at 0001.
    """
    provider = DatabaseProvider.from_url(global_url)
    try:
        async with provider.session() as session:
            table_exists = await session.execute(text("SELECT to_regclass('ip.connections')"))
            if table_exists.scalar() is None:
                return

            reconciled_count = 0
            chunk_stmt = text(
                """
                WITH batch AS (
                    SELECT id
                    FROM ip.connections
                    WHERE auth_type = 'NO_AUTH' AND status = 'PENDING_AUTH'
                    LIMIT :batch_size
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE ip.connections AS target
                SET status = 'ACTIVE', updated_at = NOW()
                FROM batch
                WHERE target.id = batch.id
                RETURNING target.id;
                """
            )
            while True:
                updated = await session.execute(
                    chunk_stmt, {"batch_size": MIGRATION_BACKFILL_BATCH_SIZE}
                )
                batch_count = len(updated.all())
                await session.commit()
                if batch_count == 0:
                    break
                reconciled_count += batch_count
                await asyncio.sleep(MIGRATION_BACKFILL_YIELD_SECONDS)

            if reconciled_count > 0:
                logger.info(
                    "ip_global_migrations_reconciled_no_auth_connections",
                    activated_count=reconciled_count,
                )

            await session.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint c
                            JOIN pg_namespace n ON n.oid = c.connamespace
                            WHERE n.nspname = 'ip'
                              AND c.conname = 'ck_ip_connections_no_auth_not_pending'
                        ) THEN
                            ALTER TABLE ip.connections
                            ADD CONSTRAINT ck_ip_connections_no_auth_not_pending
                            CHECK (NOT (auth_type = 'NO_AUTH' AND status = 'PENDING_AUTH'));
                        END IF;
                    END
                    $$;
                    """
                )
            )
            await session.commit()
    finally:
        await provider.close()


async def fetch_tenant_shard_urls(global_url: str, overrides: Mapping[str, str]) -> list[str]:
    """Connect to the global DB and fetch all registered IP shard URLs."""
    return await fetch_prefixed_shard_urls(
        global_url,
        overrides,
        shard_prefix=IP_SHARD_PREFIX,
    )


def find_ip_ini_path(ini_name: str) -> Path:
    """Locate an Alembic ini file (alembic.global.ini or alembic.tenant.ini) for apps/ip."""
    base_dir = Path(__file__).resolve().parent
    for parent in [base_dir, *list(base_dir.parents)]:
        candidate = parent / "apps" / "ip" / "packages" / "ip" / ini_name
        if candidate.exists():
            return candidate.resolve()
        candidate = parent / ini_name
        if candidate.exists() and "ip" in str(candidate):
            return candidate.resolve()

    cwd = Path.cwd()
    candidate = cwd / "apps" / "ip" / "packages" / "ip" / ini_name
    if candidate.exists():
        return candidate.resolve()

    raise FileNotFoundError(f"Could not locate {ini_name} for apps/ip/packages/ip")


def find_ip_script_location(domain: str) -> Path:
    """Locate the migration script directory ('global' or 'tenant')."""
    base_dir = Path(__file__).resolve().parent
    local_dir = base_dir / "migrations" / domain
    if local_dir.exists():
        return local_dir.resolve()

    raise FileNotFoundError(f"Could not locate IP migration scripts for '{domain}'")


def run_migrations() -> None:
    """Execute Integration Platform Control Plane (global) and Data Plane (tenant shard) migrations."""
    load_repo_env(override=False)
    settings = load_settings_safely(PlatformDatabaseSettings)
    effective_overrides = collect_ip_shard_overrides(os.environ, settings.shard_overrides)

    # 1. Global Control Plane migrations (multi-branch heads: global_engine + solution extensions)
    logger.info("ip_global_migrations_starting")
    asyncio.run(reconcile_global_alembic_branch_roots(settings.global_url))
    global_ini = find_ip_ini_path("alembic.global.ini")
    global_script_loc = find_ip_script_location("global")
    global_cfg = Config(str(global_ini))
    global_cfg.set_main_option("script_location", str(global_script_loc))
    global_cfg.set_main_option("sqlalchemy.url", settings.global_url.replace("%", "%%"))
    command.upgrade(global_cfg, "heads")
    asyncio.run(reconcile_global_no_auth_connection_constraint(settings.global_url))
    logger.info("ip_global_migrations_completed")

    # 2. Tenant Data Plane shard migrations
    shard_urls = asyncio.run(fetch_tenant_shard_urls(settings.global_url, effective_overrides))
    tenant_ini = find_ip_ini_path("alembic.tenant.ini")
    tenant_script_loc = find_ip_script_location("tenant")
    for url in shard_urls:
        tenant_cfg = Config(str(tenant_ini))
        tenant_cfg.set_main_option("script_location", str(tenant_script_loc))
        tenant_cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
        command.upgrade(tenant_cfg, "heads")

    logger.info("ip_database_migrations_completed", shards_migrated=len(shard_urls))


if __name__ == "__main__":
    run_migrations()
