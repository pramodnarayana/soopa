from dataclasses import dataclass
from typing import Protocol

from identity.domain.identity_context import IdentityContext


@dataclass(frozen=True)
class UserProfile:
    subject: str
    email: str | None = None
    display_name: str | None = None


class IdentityProviderPort(Protocol):
    async def get_user_profile(self, identity: IdentityContext) -> UserProfile: ...
