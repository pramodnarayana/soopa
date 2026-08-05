from typing import Protocol

from ucp_api.domain.models.user import User


class IUserRepository(Protocol):
    async def find_users_by_tenant(self, tenant_id: str) -> list[User]:
        """Finds all users associated with a specific tenant"""
        ...

    async def delete_orphaned_users(self, user_ids: list[str]) -> None:
        """Deletes users if they are not associated with any active tenants"""
        ...

    async def save(self, user: User) -> None:
        """Persists a User aggregate to the database."""
        ...

    async def save_tenant_membership(self, tenant_id: str, user_id: str, role: str) -> None:
        """Upserts a tenant-user relationship and role."""
        ...

    async def remove_tenant_membership(self, tenant_id: str, user_id: str) -> None:
        """Removes a user from a tenant."""
        ...

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        """Checks if a user has any tenant memberships."""
        ...
