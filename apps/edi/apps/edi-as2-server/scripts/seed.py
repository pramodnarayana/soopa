import asyncio

import structlog
from database.models.identity import Tenant
from database.router import DatabaseRouter
from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.infra.config import load_repo_env
from sqlalchemy.future import select

from as2_server.settings import get_settings as get_worker_settings

load_repo_env(override=False)

logger = structlog.get_logger(__name__)


async def seed_database() -> None:
    """Seeds the database with required initial infrastructure and default Tenant 0."""
    logger.info("as2_seed_started")
    settings = get_worker_settings()

    db_router = DatabaseRouter(settings.database.global_url)

    try:
        async with db_router.global_session_scope() as session:
            try:
                # 1. Assert Core Platform Infrastructure Exists (Read-Only)
                logger.info(
                    "as2_seed_asserting_platform_tenant",
                    tenant_id=PLATFORM_TENANT_ID,
                )
                tenant_result = await session.execute(
                    select(Tenant).filter_by(id=PLATFORM_TENANT_ID)
                )
                tenant_obj = tenant_result.scalar_one_or_none()
                if not tenant_obj:
                    logger.error(
                        "as2_seed_platform_tenant_missing",
                        tenant_id=PLATFORM_TENANT_ID,
                    )

                await session.commit()
                logger.info("as2_seed_completed")
            except Exception:
                logger.exception("as2_seed_failed")
                await session.rollback()
                raise
    finally:
        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(seed_database())
