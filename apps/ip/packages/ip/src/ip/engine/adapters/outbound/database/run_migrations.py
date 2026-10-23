"""Integration Platform hybrid multi-tenancy database migration runner (Global Control Plane + Tenant Shards)."""

import asyncio
import os
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from database.provider import get_async_engine

logger = structlog.get_logger(__name__)


async def fetch_tenant_shard_urls(global_url: str, overrides: dict[str, str]) -> list[str]:
    """Connect to the global DB and fetch all registered IP shard URLs."""
    engine = get_async_engine(global_url)
    shard_map: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT id, dsn FROM ucp.database_shards"))
            for row in result.fetchall():
                shard_id, dsn = row
                if str(shard_id).lower().startswith("ip_"):
                    shard_map[str(shard_id).lower()] = str(dsn)
    except DBAPIError as err:
        if not overrides:
            logger.error("ucp_database_shards_query_failed_no_overrides", error=str(err))
            raise
        logger.warning("ucp_database_shards_unavailable_using_overrides", error=str(err))
    finally:
        await engine.dispose()

    if overrides:
        for shard_id, dsn in overrides.items():
            if shard_id.lower().startswith("ip_"):
                shard_map[shard_id.lower()] = dsn

    return list(set(shard_map.values()))


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
    cwd = Path.cwd()
    if (cwd / ".env").exists():
        load_dotenv(cwd / ".env")
    else:
        current = Path(__file__).resolve()
        for parent in current.parents:
            if (parent / ".env").exists():
                load_dotenv(parent / ".env")
                break

    settings = load_settings_safely(PlatformDatabaseSettings)
    ip_db_url = (
        os.environ.get("IP_DATABASE_URL")
        or os.environ.get("SHARD_OVERRIDES__IP_SHARD_1")
        or settings.shard_overrides.get("ip_shard_1")
    )
    if ip_db_url:
        settings.shard_overrides["ip_shard_1"] = ip_db_url

    # 1. Global Control Plane migrations
    logger.info("ip_global_migrations_starting")
    global_ini = find_ip_ini_path("alembic.global.ini")
    global_script_loc = find_ip_script_location("global")
    global_cfg = Config(str(global_ini))
    global_cfg.set_main_option("script_location", str(global_script_loc))
    global_cfg.set_main_option("sqlalchemy.url", settings.global_url.replace("%", "%%"))
    command.upgrade(global_cfg, "head")
    logger.info("ip_global_migrations_completed")

    # 2. Tenant Data Plane shard migrations
    shard_urls = asyncio.run(fetch_tenant_shard_urls(settings.global_url, settings.shard_overrides))
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
