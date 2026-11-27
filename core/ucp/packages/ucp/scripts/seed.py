"""Seed Script — Bootstraps the platform Sentinel Tenant, canonical roles, and primary shards."""

from __future__ import annotations

import asyncio
import sys

import structlog
from database.provider import DatabaseProvider
from database.utils import normalize_to_asyncpg
from identity.config import PlatformIdentitySettings
from pydantic import AliasChoices, Field
from pydantic_settings import SettingsConfigDict
from seedwork.infra.config import CleanBaseSettings, load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings

from ucp.bootstrap.identity_bootstrap import (
    PlatformSeedConfig,
    seed_platform_bootstrap,
)

logger = structlog.get_logger(__name__)


class PlatformSeedSettings(CleanBaseSettings):
    """Typed 12-factor configuration for idempotent platform control-plane seeding."""

    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    database: PlatformDatabaseSettings = Field(default_factory=PlatformDatabaseSettings)
    identity: PlatformIdentitySettings = Field(default_factory=PlatformIdentitySettings)
    platform_admin_id: str = Field(
        validation_alias=AliasChoices("IDENTITY_PLATFORM_ADMIN_ID", "platform_admin_id"),
        min_length=1,
    )
    company_domain: str = Field(
        validation_alias=AliasChoices("COMPANY_DOMAIN", "company_domain"),
        default="flowwolf.io",
    )
    platform_admin_email_override: str = Field(
        validation_alias=AliasChoices("IDENTITY_PLATFORM_ADMIN_EMAIL", "platform_admin_email"),
        default="",
    )

    @property
    def resolved_platform_org_id(self) -> str:
        return self.identity.platform_org_id or self.identity.platform_realm

    @property
    def resolved_platform_admin_email(self) -> str:
        override = self.platform_admin_email_override.strip()
        if override:
            return override
        return f"admin@{self.company_domain.strip()}"


async def main() -> None:
    settings = load_settings_safely(PlatformSeedSettings)
    if not settings.database.global_url:
        logger.error("seed_missing_database_url")
        sys.exit(1)

    platform_org_id = settings.resolved_platform_org_id
    if not platform_org_id:
        logger.error("seed_missing_identity_platform_org_id")
        sys.exit(1)

    db_provider = DatabaseProvider.from_url(normalize_to_asyncpg(settings.database.global_url))
    try:
        await seed_platform_bootstrap(
            session_factory=db_provider.session,
            config=PlatformSeedConfig(
                platform_org_id=platform_org_id,
                platform_admin_id=settings.platform_admin_id,
                platform_admin_email=settings.resolved_platform_admin_email,
                idp_issuer=settings.identity.issuer,
            ),
        )
    except Exception:
        logger.exception("platform_bootstrap_seed_failed")
        sys.exit(1)
    finally:
        await db_provider.close()


if __name__ == "__main__":
    asyncio.run(main())
