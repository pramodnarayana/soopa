from typing import Protocol, Tuple

class IOrganizationProvider(Protocol):
    async def create_organization(self, name: str) -> Tuple[str, bool]:
        """Creates an organization and returns (org_id, grant_succeeded)"""
        ...
        
    async def delete_organization(self, org_id: str) -> None:
        """Deletes an organization"""
        ...
