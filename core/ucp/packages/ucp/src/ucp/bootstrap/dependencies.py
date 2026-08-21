from collections.abc import AsyncGenerator
from functools import lru_cache

from identity.adapters.outbound.zitadel.jwks_token_verifier_adapter import (
    ZitadelTokenVerifierPort,
    ZitadelTokenVerifierPortOptions,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.bootstrap.config import get_settings
from ucp.bootstrap.container import _async_session_maker


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with _async_session_maker() as session:
        yield session


@lru_cache(maxsize=1)
def get_token_verifier() -> ZitadelTokenVerifierPort:
    settings = get_settings()
    options = ZitadelTokenVerifierPortOptions(
        issuer=settings.zitadel_issuer,
        audience=settings.zitadel_ucp_project_id,
        platform_org_id=settings.zitadel_platform_org_id,
    )
    return ZitadelTokenVerifierPort(options)
