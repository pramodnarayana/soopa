from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IdpRole:
    key: str
    display_name: str
    group: str


@dataclass(frozen=True)
class IdpUser:
    id: str
    preferred_login_name: str
    email: str
    first_name: str
    last_name: str
    state: str


class ProjectProviderPort(Protocol):
    async def create_project_grant(
        self, org_id: str, project_id: str, role_keys: list[str]
    ) -> None:
        """Grants a project to an organization with specific roles"""
        ...

    async def delete_project_grant(self, org_id: str, project_id: str) -> None:
        """Removes a project grant from an organization"""
        ...

    async def get_roles(self, project_id: str | None = None) -> list[IdpRole]:
        """Gets all roles for the specified project (defaults to UCP project)"""
        ...

    async def get_users(self, org_id: str) -> list[IdpUser]:
        """Gets all users within a specific organization"""
        ...
