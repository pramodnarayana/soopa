import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from identity.domain.authentication_strategy import IAuthenticationStrategy
from identity.domain.identity_context import M2M_API_KEY_PREFIX, IdentityContext
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.outbound.database.postgres_api_token_repository import PostgresApiTokenRepository
from ucp.application.services.api_key_authenticator import authenticate_api_key

logger = logging.getLogger(__name__)


class ApiKeyStrategy(IAuthenticationStrategy):
    """
    Authentication strategy for Machine-to-Machine (M2M) API Keys.
    """

    def __init__(self, session_maker: Callable[[], AbstractAsyncContextManager[AsyncSession]]):
        self.session_maker = session_maker

    def can_handle(self, token: str) -> bool:
        return token.startswith(M2M_API_KEY_PREFIX)

    async def authenticate(self, token: str) -> IdentityContext:
        logger.error("[ApiKeyStrategy] Token identified as M2M API Key. Processing...")

        async with self.session_maker() as session:
            token_repo = PostgresApiTokenRepository(session)
            try:
                logger.error("[ApiKeyStrategy] Calling authenticate_api_key...")
                identity = await authenticate_api_key(token, token_repo)
                logger.error(f"[ApiKeyStrategy] SUCCESS. Identity populated: {identity.subject}")
                return identity
            except Exception:
                logger.exception("[ApiKeyStrategy] CRITICAL ERROR in authenticate_api_key")
                raise
