from typing import Literal, Protocol


class IUserIdentityProvider(Protocol):
    async def create_user(
        self,
        org_id: str,
        email: str,
        first_name: str,
        last_name: str,
    ) -> str:
        """Creates a user in the IDP and returns their IDP user ID."""
        ...

    async def assign_tenant_role(self, user_id: str, org_id: str, role: str) -> None:
        """Assigns a role to a user within a specific tenant (org)."""
        ...

    async def update_tenant_role(self, user_id: str, org_id: str, role: str) -> None:
        """Updates a user's role within a specific tenant (org)."""
        ...

    async def update_user_profile(
        self,
        user_id: str,
        org_id: str,
        first_name: str,
        last_name: str,
    ) -> None:
        """Updates user's basic profile details."""
        ...

    async def delete_user(self, user_id: str) -> None:
        """Deletes user from the identity provider"""
        ...

    async def toggle_user_status(
        self,
        user_id: str,
        org_id: str,
        action: Literal["activate", "deactivate"],
    ) -> None:
        """Activates or deactivates a user"""
        ...
