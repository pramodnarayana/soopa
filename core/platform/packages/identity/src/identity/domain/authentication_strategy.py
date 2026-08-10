from abc import ABC, abstractmethod

from identity.domain.identity_context import IdentityContext


class IAuthenticationStrategy(ABC):
    """
    Interface for handling token authentication strategies in the perimeter middleware.
    Follows the Strategy Pattern (Open/Closed Principle) to allow supporting multiple
    token formats (JWT, M2M API Keys, etc.) without modifying the middleware.
    """

    @abstractmethod
    def can_handle(self, token: str) -> bool:
        """
        Evaluates whether this strategy can process the given token string.
        """
        pass

    @abstractmethod
    async def authenticate(self, token: str) -> IdentityContext:
        """
        Validates the token and returns the normalized IdentityContext.
        Raises AuthenticationError or HTTPException on failure.
        """
        pass
