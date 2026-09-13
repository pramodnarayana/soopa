from typing import Protocol


class IdentityProviderPort(Protocol):
    """
    Port for the external Identity Provider (e.g. Zitadel, Auth0).
    """

    async def sync_tenant(self, tenant_id: str) -> None:
        """
        Synchronizes a given tenant's information to the external IDP.
        """
        ...

    async def grant_project_to_organization(self, org_id: str, project_id: str) -> None: ...

    async def revoke_project_from_organization(self, org_id: str, project_id: str) -> None: ...
