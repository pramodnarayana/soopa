from typing import Protocol


class IOrganizationProvider(Protocol):
    async def create_organization(self, name: str) -> tuple[str, bool]:
        """Creates an organization and returns (org_id, grant_succeeded)"""
        ...

    async def delete_organization(self, org_id: str) -> None:
        """Deletes an organization"""
        ...

    async def update_organization_name(self, org_id: str, name: str) -> None:
        """Updates an organization's name in the IDP"""
        ...

    async def toggle_organization_status(self, org_id: str, active: bool) -> None:
        """Activates or deactivates an organization in the IDP"""
        ...
