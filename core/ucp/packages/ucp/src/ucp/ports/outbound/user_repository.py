from typing import Protocol

from ucp.domain.models.user import User


class IUserRepository(Protocol):
    async def find_users_by_tenant(self, tenant_id: str) -> list[User]:
        """Finds all users associated with a specific tenant"""
        ...

    async def find_by_email(self, email: str) -> User | None:
        """Finds a user by their email address"""
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

    async def save_tenant_membership(self, tenant_id: str, user_id: str, role: str) -> None:
        """Upserts a tenant-user relationship and role."""
        ...

    async def remove_tenant_membership(self, tenant_id: str, user: User) -> None:
        """Removes a user from a tenant and flushes events."""
        ...

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        """Checks if a user has any tenant memberships."""
        ...
