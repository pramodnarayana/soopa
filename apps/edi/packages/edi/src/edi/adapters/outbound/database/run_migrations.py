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


def find_edi_ini_path(ini_name: str) -> Path:
    """Locate an Alembic ini file (alembic.global.ini or alembic.tenant.ini)."""
    # 1. Check co-located with this module
    base_dir = Path(__file__).resolve().parent
    local_candidate = base_dir / ini_name
    if local_candidate.exists():
        return local_candidate.resolve()

    # 2. Check current working directory (e.g. /app in container or repo root locally)
    cwd = Path.cwd()
    cwd_candidates = [
        cwd / "apps" / "edi" / "packages" / "edi" / ini_name,
        cwd / ini_name,
    ]
    for candidate in cwd_candidates:
        if candidate.exists():
            return candidate.resolve()

    # 3. Search upwards from current file location (__file__)
    current = Path(__file__).resolve()
    for parent in [current, *list(current.parents)]:
        candidate = parent / "apps" / "edi" / "packages" / "edi" / ini_name
        if candidate.exists():
            return candidate.resolve()
        candidate = parent / ini_name
        if candidate.exists():
            return candidate.resolve()

    # 4. Container fallback (/app)
    container_candidate = Path("/app/apps/edi/packages/edi") / ini_name
    if container_candidate.exists():
        return container_candidate.resolve()

    raise FileNotFoundError(
        f"Could not locate {ini_name}. Ensure apps/edi/packages/edi is present."
    )


def find_edi_script_location(domain: str) -> Path:
    """Locate the migration script directory ('global' or 'tenant')."""
    base_dir = Path(__file__).resolve().parent
    local_dir = base_dir / "migrations" / domain
    if local_dir.exists():
        return local_dir.resolve()

    cwd = Path.cwd()
    cwd_candidates = [
        cwd
        / "apps"
        / "edi"
        / "packages"
        / "edi"
        / "src"
        / "edi"
        / "adapters"
        / "outbound"
        / "database"
        / "migrations"
        / domain,
    ]
    for candidate in cwd_candidates:
        if candidate.exists():
            return candidate.resolve()

    container_candidate = Path(
        f"/app/apps/edi/packages/edi/src/edi/adapters/outbound/database/migrations/{domain}"
    )
    if container_candidate.exists():
        return container_candidate.resolve()

    raise FileNotFoundError(f"Could not locate migration scripts for '{domain}'")


def run_migrations() -> None:
    """
    Runs the Global Control Plane migration, then iterates dynamically
    to apply Tenant schema migrations across all database shards.
    """
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

    # In hybrid multi-tenancy, the migrator container receives EDI_DATABASE_URL directly
    edi_db_url = os.environ.get("EDI_DATABASE_URL")
    if edi_db_url:
        settings.shard_overrides["edi_shard_1"] = edi_db_url

    # 1. Run Global Migrations
    logger.info("edi_global_migrations_starting")
    global_ini = find_edi_ini_path("alembic.global.ini")
    global_script_loc = find_edi_script_location("global")
    global_cfg = Config(str(global_ini))
    global_cfg.set_main_option("script_location", str(global_script_loc))
    command.upgrade(global_cfg, "head")
    logger.info("edi_global_migrations_completed")

    # 2. Fetch Shards dynamically
    logger.info("fetching_tenant_shards")
    shard_urls = asyncio.run(fetch_tenant_shard_urls(settings.global_url, settings.shard_overrides))
    logger.info("tenant_shards_discovered", count=len(shard_urls))

    # 3. Run Tenant Migrations per shard
    tenant_ini = find_edi_ini_path("alembic.tenant.ini")
    tenant_script_loc = find_edi_script_location("tenant")
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

        logger.info("tenant_shard_migration_starting", shard=masked_url)
        tenant_cfg = Config(str(tenant_ini))
        tenant_cfg.set_main_option("script_location", str(tenant_script_loc))
        tenant_cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

        command.upgrade(tenant_cfg, "head")
        logger.info("tenant_shard_migration_completed", shard=masked_url)

    logger.info("edi_database_migrations_completed")


if __name__ == "__main__":
    run_migrations()
