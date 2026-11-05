"""Seed Script — Bootstraps the platform Sentinel Tenant, canonical roles, and primary shards."""

from __future__ import annotations

import asyncio
import os
import sys

import structlog
from database.provider import DatabaseProvider
from database.utils import normalize_to_asyncpg
from seedwork.infra.config import load_repo_env

from ucp.bootstrap.identity_bootstrap import PlatformSeedConfig, seed_platform_bootstrap

load_repo_env(override=False)


logger = structlog.get_logger(__name__)


async def main() -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("seed_missing_database_url")
        sys.exit(1)

    platform_org_id = os.environ.get("IDENTITY_PLATFORM_ORG_ID", "")
    if not platform_org_id:
        logger.error("seed_missing_identity_platform_org_id")
        sys.exit(1)

    platform_admin_id = os.environ.get("IDENTITY_PLATFORM_ADMIN_ID", "")
    if not platform_admin_id:
        logger.error("seed_missing_identity_platform_admin_id")
        sys.exit(1)

    edi_shard_dsn = (
        os.environ.get("DATABASE__SHARD_OVERRIDES__EDI_SHARD_1")
        or os.environ.get("SHARD_OVERRIDES__EDI_SHARD_1")
        or os.environ.get("EDI_DATABASE_URL", "")
    )
    if edi_shard_dsn:
        edi_shard_dsn = normalize_to_asyncpg(edi_shard_dsn)

    edi_project_id = os.environ.get("IDENTITY_EDI_PROJECT_ID", "")

    db_provider = DatabaseProvider.from_url(normalize_to_asyncpg(database_url))
    try:
        await seed_platform_bootstrap(
            session_factory=db_provider.session,
            config=PlatformSeedConfig(
                platform_org_id=platform_org_id,
                platform_admin_id=platform_admin_id,
                edi_shard_dsn=edi_shard_dsn,
                edi_project_id=edi_project_id,
            ),
        )
    except Exception:
        logger.exception("platform_bootstrap_seed_failed")
        sys.exit(1)
    finally:
        await db_provider.close()


if __name__ == "__main__":
    asyncio.run(main())
