import asyncio
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from edi.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def fetch_tenant_shard_urls(global_url: str) -> list[str]:
    """
    Connect to the global DB and fetch all registered shard URLs.
    If none exist (e.g., initial bootstrap), fallback to defaults.
    """
    engine = create_async_engine(global_url, echo=False)
    urls = []
    try:
        async with engine.connect() as conn:
            # We don't use ORM here to keep migration runner simple and resilient
            result = await conn.execute(text("SELECT dsn FROM ucp.database_shards"))
            urls = [row[0] for row in result.fetchall()]
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

    if not urls:
        logger.info("No shards found in Global DB. Falling back to default infrastructure shards.")
        urls = [
            "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
        ]
    return urls


def run_migrations():
    """
    Runs the Global Control Plane migration, then iterates dynamically
    to apply Tenant schema migrations across all database shards.
    """
    settings = get_settings()

    # We assume the runner is executed from the repo root

    # Dynamically resolve paths relative to this script's location
    # __file__ is apps/edi/packages/edi/src/edi/adapters/outbound/database/run_migrations.py
    base_dir = Path(__file__).resolve().parent
    package_root = base_dir.parents[4]  # Go up 5 levels to apps/edi/packages/edi/

    # 1. Run Global Migrations
    logger.info("--- Applying GLOBAL DB Migrations ---")
    global_cfg = Config(str(package_root / "alembic.global.ini"))
    global_cfg.set_main_option("script_location", str(base_dir / "migrations" / "global"))
    command.upgrade(global_cfg, "head")
    logger.info("FINISHED UPGRADE")

    # 2. Fetch Shards dynamically
    logger.info("--- Fetching Tenant Shards ---")
    shard_urls = asyncio.run(fetch_tenant_shard_urls(settings.database.global_url))
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
            except Exception:  # noqa: BLE001
                masked_url = "***redacted***"

        logger.info(
            "--- Applying TENANT Migrations to Shard: {masked_url} ---", masked_url=masked_url
        )
        tenant_cfg = Config(str(package_root / "alembic.tenant.ini"))
        tenant_cfg.set_main_option("script_location", str(base_dir / "migrations" / "tenant"))
        tenant_cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(tenant_cfg, "head")
        logger.info("FINISHED TENANT UPGRADE FOR {masked_url}", masked_url=masked_url)

    logger.info("--- All Database Migrations Complete ---")


if __name__ == "__main__":
    run_migrations()
