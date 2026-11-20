"""Seed Script — Bootstraps the platform Sentinel Tenant, canonical roles, and primary shards."""

from __future__ import annotations

import asyncio
import os
import sys

import structlog
from database.provider import DatabaseProvider
from database.utils import normalize_to_asyncpg

from ucp.bootstrap.identity_bootstrap import (
    PlatformSeedConfig,
    seed_platform_bootstrap,
)
from ucp.config.settings import get_settings

logger = structlog.get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    database_url = settings.database_url
    if not database_url:
        logger.error("seed_missing_database_url")
        sys.exit(1)

    platform_org_id = settings.identity.platform_org_id or os.environ.get(
        "IDENTITY_PLATFORM_ORG_ID", ""
    )
    if not platform_org_id:
        logger.error("seed_missing_identity_platform_org_id")
        sys.exit(1)

    platform_admin_id = os.environ.get("IDENTITY_PLATFORM_ADMIN_ID", "")
    if not platform_admin_id:
        logger.error("seed_missing_identity_platform_admin_id")
        sys.exit(1)

    company_domain = os.environ.get("COMPANY_DOMAIN", "flowwolf.io").strip()
    platform_admin_email = (
        os.environ.get("IDENTITY_PLATFORM_ADMIN_EMAIL", "").strip() or f"admin@{company_domain}"
    )

    db_provider = DatabaseProvider.from_url(normalize_to_asyncpg(database_url))
    try:
        await seed_platform_bootstrap(
            session_factory=db_provider.session,
            config=PlatformSeedConfig(
                platform_org_id=platform_org_id,
                platform_admin_id=platform_admin_id,
                platform_admin_email=platform_admin_email,
            ),
        )
    except Exception:
        logger.exception("platform_bootstrap_seed_failed")
        sys.exit(1)
    finally:
        await db_provider.close()


if __name__ == "__main__":
    asyncio.run(main())
