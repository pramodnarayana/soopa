import logging
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from identity.domain.authentication_strategy import IAuthenticationStrategy
from identity.domain.identity_context import M2M_API_KEY_PREFIX, IdentityContext

from ucp.application.services.api_key_authenticator import authenticate_api_key
from ucp.ports.api_token_repository import ApiTokenRepositoryPort

logger = logging.getLogger(__name__)


class ApiKeyStrategy(IAuthenticationStrategy):
    """
    Authentication strategy for Machine-to-Machine (M2M) API Keys.
    """

    def __init__(
        self, token_repo_factory: Callable[[], AbstractAsyncContextManager[ApiTokenRepositoryPort]]
    ):
        self.token_repo_factory = token_repo_factory

    def can_handle(self, token: str) -> bool:
        return token.startswith(M2M_API_KEY_PREFIX)

    async def authenticate(self, token: str) -> IdentityContext:
        logger.debug("[ApiKeyStrategy] Token identified as M2M API Key. Processing...")

        async with self.token_repo_factory() as token_repo:
            try:
                logger.debug("[ApiKeyStrategy] Calling authenticate_api_key...")
                identity = await authenticate_api_key(token, token_repo)
                logger.debug(f"[ApiKeyStrategy] SUCCESS. Identity populated: {identity.subject}")
                return identity
            except Exception:
                logger.exception("[ApiKeyStrategy] CRITICAL ERROR in authenticate_api_key")
                raise
