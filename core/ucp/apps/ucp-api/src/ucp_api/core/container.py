"""
Infrastructure factories for the UCP API.

Single responsibility: own the SQLAlchemy engine + session factory and the
ZitadelTokenVerifier singleton. All other wiring happens in main.py.
"""

from functools import lru_cache
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from identity.adapters.outbound.zitadel.jwks_token_verifier import (
    ZitadelTokenVerifier,
    ZitadelTokenVerifierOptions,
)

from ucp_api.core.config import get_settings

_settings = get_settings()
_engine = create_async_engine(
    _settings.database_url,
    echo=False,
    # Proactively check connections before use to avoid stale pool entries.
    pool_pre_ping=True,
)
_async_session_maker = async_sessionmaker(
    _engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that yields a request-scoped AsyncSession wrapped in an
    explicit transaction.

    On success the transaction is committed automatically when the context exits.
    On any unhandled exception the transaction rolls back, preventing partial
    writes (e.g. Zitadel org created but DB tenant row missing).
    """
    async with _async_session_maker() as session:
        async with session.begin():
            yield session


@lru_cache(maxsize=1)
def get_token_verifier() -> ZitadelTokenVerifier:
    """
    Returns a process-level singleton ZitadelTokenVerifier.

    Using @lru_cache ensures exactly ONE instance is created per process,
    so there is a single shared JWKS key cache regardless of how many
    guards import this function.
    """
    settings = get_settings()
    options = ZitadelTokenVerifierOptions(
        issuer=settings.zitadel_issuer,
        audience=settings.zitadel_ucp_project_id,
        platform_org_id=settings.zitadel_platform_org_id,
    )
    return ZitadelTokenVerifier(options)
