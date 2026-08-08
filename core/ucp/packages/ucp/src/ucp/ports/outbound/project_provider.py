from typing import Protocol

from ucp.domain.dtos.zitadel_dtos import ZitadelRole, ZitadelUser


class IProjectProvider(Protocol):
    async def create_project_grant(
        self, org_id: str, project_id: str, role_keys: list[str]
    ) -> None:
        """Grants a project to an organization with specific roles"""
        ...

    async def delete_project_grant(self, org_id: str, project_id: str) -> None:
        """Removes a project grant from an organization"""
        ...

    async def get_roles(self) -> list[ZitadelRole]:
        """Gets all roles for the UCP project"""
        ...

    async def get_users(self, org_id: str) -> list[ZitadelUser]:
        """Gets all users with access to this project in a specific org"""
        ...
