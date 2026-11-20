"""Seeds Integration Platform (IP) bounded-context shard and application metadata into global_db."""

from __future__ import annotations

import asyncio
import os
import sys

import structlog
from database.models.identity import Tenant
from database.provider import DatabaseProvider
from database.utils import normalize_to_asyncpg
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.infra.config import load_settings_safely
from seedwork.infra.config_models import PlatformDatabaseSettings
from sharding.domain.constants import DatabaseShardStatus
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from ucp_models.sharding import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

logger = structlog.get_logger(__name__)

IP_APP_ID = "app_ip_core"
IP_APP_SLUG = "ip"
IP_SHARD_ID = "ip_shard_1"


async def seed_ip_domain() -> None:
    """Idempotently seeds the IP primary database shard, application record, and default shard binding."""
    settings = load_settings_safely(PlatformDatabaseSettings)
    database_url = settings.global_url

    ip_shards: dict[str, str] = {}
    for shard_key, dsn in settings.shard_overrides.items():
        if shard_key.lower().startswith("ip_"):
            ip_shards[shard_key.lower()] = normalize_to_asyncpg(dsn)

    default_ip_dsn = os.environ.get("IP_DATABASE_URL", "")
    if not ip_shards and default_ip_dsn:
        ip_shards[IP_SHARD_ID] = normalize_to_asyncpg(default_ip_dsn)

    provider = DatabaseProvider.from_url(database_url)
    try:
        async with provider.session() as session:
            stmt_app = (
                pg_insert(App)
                .values(
                    id=IP_APP_ID,
                    slug=IP_APP_SLUG,
                    name="Integration Platform",
                    description="Enterprise Integration Platform (iPaaS)",
                )
                .on_conflict_do_update(
                    index_elements=[App.slug],
                    set_={
                        "name": "Integration Platform",
                        "description": "Enterprise Integration Platform (iPaaS)",
                    },
                )
                .returning(App.id)
            )
            app_res = await session.execute(stmt_app)
            actual_app_id = str(app_res.scalar_one())
            logger.info("ip_seed_app_registered", app_id=actual_app_id, slug=IP_APP_SLUG)

            if ip_shards:
                for shard_id, shard_dsn in ip_shards.items():
                    shard_name = f"IP Shard ({shard_id})"
                    stmt_shard = (
                        pg_insert(DatabaseShard)
                        .values(
                            id=shard_id,
                            name=shard_name,
                            dsn=shard_dsn,
                            status=DatabaseShardStatus.ACTIVE,
                        )
                        .on_conflict_do_update(
                            index_elements=[DatabaseShard.id],
                            set_={
                                "name": shard_name,
                                "dsn": shard_dsn,
                                "status": DatabaseShardStatus.ACTIVE,
                            },
                        )
                    )
                    await session.execute(stmt_shard)
                    logger.info("ip_seed_shard_registered", shard_id=shard_id)

                    tenants_res = await session.execute(select(Tenant.id))
                    tenant_ids = set(tenants_res.scalars().all())
                    tenant_ids.add(PLATFORM_TENANT_ID)
                    for t_id in tenant_ids:
                        stmt_binding = (
                            pg_insert(ShardRegistry)
                            .values(
                                tenant_id=t_id,
                                app_id=actual_app_id,
                                shard_id=shard_id,
                            )
                            .on_conflict_do_nothing(
                                index_elements=[ShardRegistry.tenant_id, ShardRegistry.app_id],
                            )
                        )
                        await session.execute(stmt_binding)
                        logger.info(
                            "ip_seed_tenant_shard_bound",
                            tenant_id=t_id,
                            shard_id=shard_id,
                        )
            else:
                logger.info("ip_seed_shard_skipped_no_dsn")

            await session.commit()
            logger.info("ip_seed_completed")
    except Exception:
        logger.exception("ip_seed_failed")
        sys.exit(1)
    finally:
        await provider.close()


if __name__ == "__main__":
    asyncio.run(seed_ip_domain())
