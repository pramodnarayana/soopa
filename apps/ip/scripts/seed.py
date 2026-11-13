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
from seedwork.infra.config import load_repo_env
from sharding.domain.constants import DatabaseShardStatus
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from ucp_models.sharding import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

load_repo_env(override=False)

logger = structlog.get_logger(__name__)

IP_APP_ID = "app_ip_core"
IP_APP_SLUG = "ip"
IP_SHARD_ID = "ip_shard_1"


async def seed_ip_domain() -> None:
    """Idempotently seeds the IP primary database shard, application record, and default shard binding."""
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        logger.error("ip_seed_missing_database_url")
        sys.exit(1)

    ip_shard_dsn = (
        os.environ.get("DATABASE__SHARD_OVERRIDES__IP_SHARD_1")
        or os.environ.get("SHARD_OVERRIDES__IP_SHARD_1")
        or os.environ.get("IP_DATABASE_URL", "")
    )
    if ip_shard_dsn:
        ip_shard_dsn = normalize_to_asyncpg(ip_shard_dsn)

    provider = DatabaseProvider.from_url(normalize_to_asyncpg(database_url))
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

            if ip_shard_dsn:
                stmt_shard = (
                    pg_insert(DatabaseShard)
                    .values(
                        id=IP_SHARD_ID,
                        name="IP Primary Shard",
                        dsn=ip_shard_dsn,
                        status=DatabaseShardStatus.ACTIVE,
                    )
                    .on_conflict_do_update(
                        index_elements=[DatabaseShard.id],
                        set_={
                            "name": "IP Primary Shard",
                            "dsn": ip_shard_dsn,
                            "status": DatabaseShardStatus.ACTIVE,
                        },
                    )
                )
                await session.execute(stmt_shard)
                logger.info("ip_seed_shard_registered", shard_id=IP_SHARD_ID)

                tenants_res = await session.execute(select(Tenant.id))
                tenant_ids = set(tenants_res.scalars().all())
                tenant_ids.add(PLATFORM_TENANT_ID)
                for t_id in tenant_ids:
                    stmt_binding = (
                        pg_insert(ShardRegistry)
                        .values(
                            tenant_id=t_id,
                            app_id=actual_app_id,
                            shard_id=IP_SHARD_ID,
                        )
                        .on_conflict_do_nothing(
                            index_elements=[ShardRegistry.tenant_id, ShardRegistry.app_id],
                        )
                    )
                    await session.execute(stmt_binding)
                    logger.info(
                        "ip_seed_tenant_shard_bound",
                        tenant_id=t_id,
                        shard_id=IP_SHARD_ID,
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
