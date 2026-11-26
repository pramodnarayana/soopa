from typing import Protocol

from identity.domain.constants import MembershipScope, MembershipStatus
from identity.domain.user import User


class UserRepositoryPort(Protocol):
    async def find_users_by_tenant(self, tenant_id: str) -> list[User]:
        """Finds all users associated with a specific tenant"""
        ...

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        """Checks if a user belongs to any active tenants"""
        ...

    async def upsert_tenant_membership(
        self,
        *,
        tenant_id: str,
        user_id: str,
        scope: MembershipScope = MembershipScope.DIRECT,
        status: MembershipStatus = MembershipStatus.ACTIVE,
    ) -> None:
        """Creates or updates a user's membership ledger entry in `identity.tenant_users`."""
        ...

    async def remove_tenant_membership(self, *, tenant_id: str, user_id: str) -> None:
        """Removes a user's membership ledger entry from `identity.tenant_users`."""
        ...

    async def find_by_email(self, email: str) -> User | None:
        """Finds a user by their email address"""
        ...

    async def find_by_id(self, user_id: str) -> User | None:
        """Finds a user by ID independent of tenant context."""
        ...

    async def find_by_idp_user_id(self, idp_user_id: str) -> User | None:
        """Finds a user by their external Identity Provider User ID."""
        ...

    async def find_by_id_and_tenant(self, user_id: str, tenant_id: str) -> User | None:
        """Finds a user by ID within a specific tenant context."""
        ...

    async def delete(self, user: User) -> None:
        """Delete a user."""
        ...

    async def save(self, user: User) -> None:
        """Persists a User aggregate to the database."""
        ...
