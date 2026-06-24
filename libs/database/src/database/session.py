"""
FastAPI dependency for injecting an async SQLAlchemy session.
Use with `Depends(get_session)` in FastAPI route handlers.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from .connection import AsyncSessionFactory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a database session per request.
    The session is automatically closed and returned to the pool on exit.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
