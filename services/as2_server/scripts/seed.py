import asyncio
import contextlib
import logging

from config.settings import get_settings
from database.connection import DatabaseRouter
from database.models import DatabaseShard, Tenant, TenantUser, User
from sqlalchemy.future import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed_database() -> None:
    """Seeds the database with required initial infrastructure and default Tenant 0."""
    logger.info("Starting database seed...")
    settings = get_settings()

    db_router = DatabaseRouter(settings.database.global_url)

    async_gen = db_router.get_global_session()
    session = await async_gen.__anext__()

    try:
        # 1. Seed Database Shards
        logger.info("Seeding Database Shards...")
        shard_result = await session.execute(select(DatabaseShard).filter_by(name="shard_1"))
        shard = shard_result.scalar_one_or_none()

        if not shard or not shard.id:
            shard = DatabaseShard(
                name="shard_1",
                dsn="postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
            )
            session.add(shard)
            await session.flush()  # To get the ID
            logger.info("Created shard_1.")

        # 2. Seed Default Tenant 0
        logger.info("Seeding Host Company as Tenant 0...")
        tenant_result = await session.execute(select(Tenant).filter_by(id=0))
        tenant_obj = tenant_result.scalar_one_or_none()

        if not tenant_obj:
            tenant_obj = Tenant(id=0, name="Host Company", shard_id=shard.id, tier="standard")
            session.add(tenant_obj)
            await session.flush()
            logger.info("Created Tenant 0 (Host Company).")

        # 3. Seed Default User
        logger.info("Seeding Default User...")
        user_result = await session.execute(
            select(User).filter_by(email="pramod.narayana@gmail.com")
        )
        user = user_result.scalar_one_or_none()

        if not user or not user.id:
            user = User(email="pramod.narayana@gmail.com", name="Pramod Narayana")
            session.add(user)
            await session.flush()
            logger.info("Created Admin User.")

            # Map user to Tenant 0
            tenant_user = TenantUser(tenant_id=tenant_obj.id, user_id=user.id, role="admin")
            session.add(tenant_user)
            logger.info("Mapped Admin User to Tenant 0.")

        await session.commit()
        logger.info("Database seed completed successfully.")

    except Exception as e:
        logger.error(f"Seed failed: {e}")
        await session.rollback()
    finally:
        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()
        await db_router.close_all()


if __name__ == "__main__":
    asyncio.run(seed_database())
