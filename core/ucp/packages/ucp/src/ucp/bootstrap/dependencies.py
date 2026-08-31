from collections.abc import AsyncGenerator
from functools import lru_cache

from database.provider import DatabaseProvider
from fastapi import Request
from identity.adapters.outbound.zitadel.jwks_token_verifier_adapter import (
    ZitadelTokenVerifierPort,
    ZitadelTokenVerifierPortOptions,
)
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.bootstrap.config import get_settings


async def get_db_session(request: Request) -> AsyncGenerator[AsyncSession, None]:
    db_provider: DatabaseProvider = request.app.state.db_provider
    async with db_provider.session() as session:
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
