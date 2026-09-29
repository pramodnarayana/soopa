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

from database.provider import get_async_engine

logger = structlog.get_logger(__name__)


async def fetch_tenant_shard_urls(global_url: str, overrides: dict[str, str]) -> list[str]:
    """
    Connect to the global DB and fetch all registered shard URLs.
    If none exist (e.g., initial bootstrap), fallback to defaults.
    """
    engine = get_async_engine(global_url)
    shard_map: dict[str, str] = {}
    try:
        async with engine.connect() as conn:
            # We don't use ORM here to keep migration runner simple and resilient
            result = await conn.execute(text("SELECT id, dsn FROM ucp.database_shards"))
            for row in result.fetchall():
                shard_id, dsn = row
                shard_map[shard_id] = dsn
    except Exception as e:
        # Check for SQLSTATE codes indicating missing database objects:
        # 42P01 = undefined_table, 3F000 = invalid_schema_name
        sqlstate = getattr(e, "orig", e)
        pgcode = getattr(sqlstate, "pgcode", None)
        if pgcode in ("42P01", "3F000"):
            logger.info("ucp.database_shards does not exist yet. Falling back to default shards.")
        else:
            logger.exception("Failed to query database_shards from global DB")
            raise
    finally:
        await engine.dispose()

    # Merge overrides (they take precedence and add new ones like edi_shard_1)
    if overrides:
        for shard_id, dsn in overrides.items():
            shard_map[shard_id] = dsn

    if not shard_map:
        logger.info(
            "No shards found in Global DB and no overrides provided. Skipping tenant migrations."
        )

    # Deduplicate URLs in case multiple shard IDs point to the same database
    return list(set(shard_map.values()))


def run_migrations():
    """
    Runs the Global Control Plane migration, then iterates dynamically
    to apply Tenant schema migrations across all database shards.
    """
    # Dynamically resolve paths relative to this script's location
    base_dir = Path(__file__).resolve().parent
    package_root = base_dir.parents[4]  # apps/edi/packages/edi/
    monorepo_root = package_root.parents[3]  # /
    load_dotenv(monorepo_root / ".env")

    settings = load_settings_safely(PlatformDatabaseSettings)

    # In hybrid multi-tenancy, the migrator container receives EDI_DATABASE_URL directly

    edi_db_url = os.environ.get("EDI_DATABASE_URL")
    if edi_db_url:
        settings.shard_overrides["edi_shard_1"] = edi_db_url

    # We assume the runner is executed from the repo root

    # 1. Run Global Migrations
    logger.info("--- Applying GLOBAL DB Migrations ---")
    global_cfg = Config(str(package_root / "alembic.global.ini"))
    global_cfg.set_main_option("script_location", str(base_dir / "migrations" / "global"))
    command.upgrade(global_cfg, "head")
    logger.info("FINISHED UPGRADE")

    # 2. Fetch Shards dynamically
    logger.info("--- Fetching Tenant Shards ---")
    shard_urls = asyncio.run(fetch_tenant_shard_urls(settings.global_url, settings.shard_overrides))
    logger.info("Found {len(shard_urls)} shard(s) to migrate", val_0=len(shard_urls))

    # 3. Run Tenant Migrations per shard
    for url in shard_urls:
        # Simple string masking to hide password if URL matches postgresql+...://user:pass@...
        masked_url = url
        if "@" in url and ":" in url:
            try:
                protocol, rest = url.split("://", 1)
                credentials, host_info = rest.split("@", 1)
                user = credentials.split(":", 1)[0]
                masked_url = f"{protocol}://{user}:***@{host_info}"
            except ValueError:
                masked_url = "***redacted***"

        logger.info(
            "--- Applying TENANT Migrations to Shard: {masked_url} ---", masked_url=masked_url
        )
        tenant_cfg = Config(str(package_root / "alembic.tenant.ini"))
        tenant_cfg.set_main_option("script_location", str(base_dir / "migrations" / "tenant"))
        tenant_cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

        # We no longer create 'edi' schema here because tenant databases should use the 'public' schema
        # asyncio.run(ensure_schema_exists(url, "edi"))

        command.upgrade(tenant_cfg, "head")
        logger.info("FINISHED TENANT UPGRADE FOR {masked_url}", masked_url=masked_url)

    logger.info("--- All Database Migrations Complete ---")


if __name__ == "__main__":
    run_migrations()
