import asyncio
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from config.settings import get_settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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
            result = await conn.execute(text("SELECT dsn FROM database_shards"))
            urls = [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"Failed to query database_shards from global DB: {e}")
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
    # __file__ is run_migrations.py, so parent is src/database/
    base_dir = Path(__file__).resolve().parent
    package_root = base_dir.parent.parent  # Go up to apps/edi/packages/database/

    # 1. Run Global Migrations
    logger.info("--- Applying GLOBAL DB Migrations ---")
    global_cfg = Config(str(package_root / "alembic.global.ini"))
    global_cfg.set_main_option("script_location", str(base_dir / "migrations" / "global"))
    command.upgrade(global_cfg, "head")

    # 2. Fetch Shards dynamically
    logger.info("--- Fetching Tenant Shards ---")
    shard_urls = asyncio.run(fetch_tenant_shard_urls(settings.database.global_url))

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
            except Exception:
                masked_url = "***redacted***"

        logger.info(f"--- Applying TENANT Migrations to Shard: {masked_url} ---")
        tenant_cfg = Config(str(package_root / "alembic.tenant.ini"))
        tenant_cfg.set_main_option("script_location", str(base_dir / "migrations" / "tenant"))
        tenant_cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(tenant_cfg, "head")

    logger.info("--- All Database Migrations Complete ---")


if __name__ == "__main__":
    run_migrations()
