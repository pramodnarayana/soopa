"""
Async SQLAlchemy engine and session factory.
Configured via environment variable DATABASE_URL.
"""

from config.settings import get_settings
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

settings = get_settings()

engine = create_async_engine(
    settings.database.url,
    echo=False,
    pool_pre_ping=True,  # Ensures stale connections are not reused
    pool_size=settings.database.pool_size,
    max_overflow=settings.database.max_overflow,
)

AsyncSessionFactory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Prevents lazy load errors after commit in async context
)
