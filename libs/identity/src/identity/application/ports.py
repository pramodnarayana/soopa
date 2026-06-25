from typing import Protocol


class IIdentityRepository(Protocol):
    """
    Port for identity and tenant operations.
    Hides all database-specific implementation details.
    """

    async def get_user_id_by_email(self, email: str) -> int | None:
        """Returns the internal User ID if the email exists, else None."""
        ...

    async def get_tenant_id_for_user(self, user_id: int) -> int | None:
        """Returns the Tenant ID mapped to the given User ID, else None."""
        ...

    async def provision_tenant_for_user(self, email: str, name: str) -> int:
        """
        Creates a new User, a new Tenant (on a default shard), and links them.
        Must be executed as an atomic transaction.
        Returns the new Tenant ID.
        """
        ...
