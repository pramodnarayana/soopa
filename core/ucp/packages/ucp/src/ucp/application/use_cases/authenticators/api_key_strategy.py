from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

import structlog
from identity.domain.authentication_strategy import IAuthenticationStrategy
from identity.domain.identity_context import M2M_API_KEY_PREFIX, IdentityContext

from ucp.application.use_cases.api_key_authenticator import authenticate_api_key
from ucp.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort

logger = structlog.get_logger(__name__)


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
        logger.debug("api_key_authentication_started")

        async with self.token_repo_factory() as token_repo:
            try:
                logger.debug("calling_authenticate_api_key")
                identity = await authenticate_api_key(token, token_repo)
                logger.debug("api_key_authentication_success", subject=identity.subject)
                return identity
            except Exception:
                logger.exception("api_key_authentication_error")
                raise
