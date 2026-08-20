from typing import Protocol

from pydantic import BaseModel

from identity.domain.identity_context import IdentityContext


class UserProfile(BaseModel):
    subject: str
    email: str | None = None
    display_name: str | None = None


class IdentityProviderPort(Protocol):
    async def get_user_profile(self, identity: IdentityContext) -> UserProfile: ...
