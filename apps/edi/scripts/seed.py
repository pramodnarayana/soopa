"""Seeds EDI application registration, metadata, and dynamic database shards into global_db."""

from __future__ import annotations

import asyncio
import os

import structlog
from database.models.subscriptions import App
from database.provider import DatabaseProvider
from database.utils import normalize_to_asyncpg
from pydantic import Field
from seedwork.infra.config import CleanBaseSettings, load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sharding.domain.constants import DatabaseShardStatus, ShardRoutingStrategy
from sqlalchemy.dialects.postgresql import insert as pg_insert
from ucp_models.sharding import DatabaseShard

logger = structlog.get_logger(__name__)

EDI_APP_ID = "app_edi_core"
EDI_APP_SLUG = "edi"


class EdiSeedSettings(CleanBaseSettings):
    database: PlatformDatabaseSettings = Field(default_factory=PlatformDatabaseSettings)
    edi_project_id: str = Field(validation_alias="IDENTITY_EDI_PROJECT_ID", default="")


async def seed_edi_domain() -> None:
    """Idempotently registers EDI application metadata and dynamic database shards into global_db."""
    settings = load_settings_safely(EdiSeedSettings)
    database_url = settings.database.global_url

    provider = DatabaseProvider.from_url(database_url)
    try:
        async with provider.session() as session:
            # 1. Register EDI Application Record with Zitadel Project ID
            stmt_app = (
                pg_insert(App)
                .values(
                    id=EDI_APP_ID,
                    slug=EDI_APP_SLUG,
                    name="EDI",
                    description="B2B Electronic Data Interchange.",
                    idp_project_id=settings.edi_project_id or None,
                )
                .on_conflict_do_update(
                    index_elements=[App.slug],
                    set_={
                        "name": "EDI",
                        "description": "B2B Electronic Data Interchange.",
                        "idp_project_id": settings.edi_project_id or None,
                    },
                )
                .returning(App.id)
            )
            app_res = await session.execute(stmt_app)
            actual_app_id = str(app_res.scalar_one())
            logger.info(
                "edi_seed_app_registered",
                app_id=actual_app_id,
                slug=EDI_APP_SLUG,
                idp_project_id=settings.edi_project_id,
            )

            # 2. Discover and Register Dynamic EDI Shards
            edi_shards: dict[str, str] = {}
            for shard_key, dsn in settings.database.shard_overrides.items():
                if shard_key.lower().startswith("edi_"):
                    edi_shards[shard_key.lower()] = normalize_to_asyncpg(dsn)

            # Fallback to default EDI_DATABASE_URL if no explicit overrides provided
            default_edi_dsn = os.environ.get("EDI_DATABASE_URL") or os.environ.get("EDI_DB_HOST")
            if not edi_shards and default_edi_dsn:
                edi_shards["edi_shard_1"] = normalize_to_asyncpg(default_edi_dsn)

            for shard_id, shard_dsn in edi_shards.items():
                shard_name = f"EDI Shard ({shard_id})"
                stmt_shard = (
                    pg_insert(DatabaseShard)
                    .values(
                        id=shard_id,
                        name=shard_name,
                        dsn=shard_dsn,
                        status=DatabaseShardStatus.ACTIVE.value,
                        routing_strategy=ShardRoutingStrategy.TENANT_REGISTRY.value,
                    )
                    .on_conflict_do_update(
                        index_elements=[DatabaseShard.id],
                        set_={
                            "name": shard_name,
                            "dsn": shard_dsn,
                            "status": DatabaseShardStatus.ACTIVE.value,
                            "routing_strategy": ShardRoutingStrategy.TENANT_REGISTRY.value,
                        },
                    )
                )
                await session.execute(stmt_shard)
                logger.info("edi_seed_shard_registered", shard_id=shard_id, name=shard_name)

            await session.commit()
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(seed_edi_domain())
