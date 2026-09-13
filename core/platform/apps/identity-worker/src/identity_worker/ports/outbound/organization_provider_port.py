from typing import Protocol


class OrganizationProviderPort(Protocol):
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

    async def grant_project_to_organization(self, org_id: str, project_id: str) -> None:
        """Grants a project and its tenant roles to an organization"""
        ...

    async def revoke_project_from_organization(self, org_id: str, project_id: str) -> None:
        """Revokes a project from an organization"""
        ...
