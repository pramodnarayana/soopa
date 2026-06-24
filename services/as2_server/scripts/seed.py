import asyncio
import logging

from database.connection import engine
from database.models import Base, Tenant
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def seed_database():
    """Seeds the database with required initial data like the default Tenant."""
    logger.info("Starting database seed...")

    # Ensure tables exist (just in case)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        # Seed Default Tenant
        result = await session.execute(select(Tenant).filter_by(id=1))
        tenant = result.scalar_one_or_none()

        if not tenant:
            logger.info("Seeding Default EDI AS2 Tenant (ID: 1)...")
            tenant = Tenant(id=1, name="Default EDI AS2 Tenant")
            session.add(tenant)
            await session.commit()
            logger.info("Default Tenant seeded successfully.")
        else:
            logger.info("Default Tenant already exists.")


if __name__ == "__main__":
    asyncio.run(seed_database())
