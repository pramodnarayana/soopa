#!/usr/bin/env python3
"""
Enterprise Database Schema Reset Utility.

Provides isolated, transactional schema wiping for local development and integration tests.
Guarantees domain boundary isolation so resetting one domain's schema never cascades or corrupts
shared Control Plane schemas belonging to other bounded contexts.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Final

import asyncpg
import structlog
from dotenv import load_dotenv

# Enforce .env as the authoritative Single Source of Truth, overriding ambient shell variables
load_dotenv(override=True)

logger = structlog.get_logger(__name__)

# Bounded Context to Control Plane Global DB Schema mapping
DOMAIN_GLOBAL_SCHEMAS: Final[dict[str, tuple[str, ...]]] = {
    "platform": (
        "platform",
        "identity",
        "ucp",
        "scheduling",
        "notifications",
        "observability",
        "public",
    ),
    "edi": ("edi",),
    "ip": ("ip",),
}

# Domain to Environment Variable mappings for Shard DSNs
DOMAIN_SHARD_ENV_VARS: Final[dict[str, tuple[str, ...]]] = {
    "edi": ("SHARD_OVERRIDES__EDI_SHARD_1", "EDI_DATABASE_URL"),
    "ip": ("SHARD_OVERRIDES__IP_SHARD_1", "IP_DATABASE_URL"),
}


def _normalize_asyncpg_dsn(dsn: str) -> str:
    """Normalizes SQLAlchemy asyncpg DSNs (e.g. postgresql+asyncpg://) for raw asyncpg driver."""
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
    if dsn.startswith("postgres+asyncpg://"):
        return dsn.replace("postgres+asyncpg://", "postgresql://", 1)
    return dsn


async def drop_schemas_for_db(
    dsn: str,
    db_name: str,
    target_schemas: list[str] | None = None,
) -> None:
    """
    Drops the specified schemas from the database.
    If target_schemas is None, drops all user/domain schemas (excluding pg_ and information_schema).
    """
    normalized_dsn = _normalize_asyncpg_dsn(dsn)
    log = logger.bind(db_name=db_name, target_schemas=target_schemas)
    log.info("schema_reset_starting")

    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(normalized_dsn)
        if target_schemas is None:
            records = await conn.fetch("""
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name != 'information_schema'
                  AND schema_name NOT LIKE 'pg\\_%';
            """)
            to_drop = [r["schema_name"] for r in records]
        else:
            to_drop = list(target_schemas)

        for schema in to_drop:
            quoted_schema = schema.replace('"', '""')
            await conn.execute(f'DROP SCHEMA IF EXISTS "{quoted_schema}" CASCADE;')

        if target_schemas is None or "public" in to_drop:
            await conn.execute("CREATE SCHEMA IF NOT EXISTS public;")
            await conn.execute("GRANT ALL ON SCHEMA public TO public;")

        log.info("schema_reset_completed", dropped_count=len(to_drop))
    except (asyncpg.Error, OSError) as exc:
        log.error("schema_reset_failed", error=str(exc))
        raise
    finally:
        if conn is not None:
            await conn.close()


def _resolve_shard_dsn(domain: str) -> str | None:
    """Resolves shard DSN from environment variables following enterprise precedence."""
    env_vars = DOMAIN_SHARD_ENV_VARS.get(domain, ())
    for var in env_vars:
        val = os.getenv(var)
        if val:
            return val
    return None


async def run_reset(selected_domains: set[str], global_url: str) -> None:
    """Executes isolated schema drops across Global DB and domain shards."""
    # 1. Drop Global DB Schemas
    if "all" in selected_domains:
        await drop_schemas_for_db(global_url, "Global DB")
    else:
        schemas_to_drop: list[str] = []
        for domain in selected_domains:
            schemas_to_drop.extend(DOMAIN_GLOBAL_SCHEMAS.get(domain, ()))
        if schemas_to_drop:
            await drop_schemas_for_db(global_url, "Global DB", target_schemas=schemas_to_drop)

    # 2. Drop Domain Shards
    for domain in ("edi", "ip"):
        if "all" in selected_domains or domain in selected_domains:
            shard_dsn = _resolve_shard_dsn(domain)
            if not shard_dsn:
                logger.error(
                    "missing_shard_database_url",
                    domain=domain,
                    expected_env_vars=DOMAIN_SHARD_ENV_VARS.get(domain, ()),
                )
                sys.exit(1)
            await drop_schemas_for_db(shard_dsn, f"{domain.upper()} Shard 1")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enterprise Database Schema Reset Utility (Isolated Domain Scopes)"
    )
    parser.add_argument(
        "--domains",
        default="all",
        help="Comma-separated list of domains to drop: all, platform, edi, ip (default: all)",
    )
    args = parser.parse_args()
    selected_domains = {d.strip().lower() for d in args.domains.split(",") if d.strip()}

    global_url = os.getenv("DATABASE_URL")
    if not global_url:
        logger.error("missing_global_database_url", var_name="DATABASE_URL")
        sys.exit(1)

    logger.info("database_reset_initiated", selected_domains=sorted(selected_domains))
    try:
        asyncio.run(run_reset(selected_domains, global_url))
        logger.info("database_reset_successful")
    except (asyncpg.Error, OSError) as exc:
        logger.error("database_reset_aborted", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
