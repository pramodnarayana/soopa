import asyncio
import contextlib

import structlog
from database.models.identity import Tenant
from dotenv import load_dotenv
from edi.adapters.outbound.database.connection import DatabaseRouter
from edi.config.settings import get_settings
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy.future import select

load_dotenv()

logger = structlog.get_logger(__name__)


async def seed_database() -> None:
    """Seeds the database with required initial infrastructure and default Tenant 0."""
    logger.info("Starting database seed...")
    settings = get_settings()

    db_router = DatabaseRouter(settings.database.global_url)

    async_gen = db_router.get_global_session()
    session = await async_gen.__anext__()

    try:
        # 1. Assert Core Platform Infrastructure Exists (Read-Only)
        logger.info("Asserting Platform Infrastructure (Tenant %s)...", PLATFORM_TENANT_ID)
        tenant_result = await session.execute(select(Tenant).filter_by(id=PLATFORM_TENANT_ID))
        tenant_obj = tenant_result.scalar_one_or_none()
        if not tenant_obj:
            logger.warning(
                "Platform Master Tenant not found! Ensure UCP seed.ts has been run first."
            )

        await session.commit()
        logger.info("Database seed completed successfully.")

    except Exception:
        logger.exception("Seed failed")

        await session.rollback()
        raise
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()
        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(seed_database())
