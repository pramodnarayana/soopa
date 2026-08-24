from dataclasses import dataclass


@dataclass(frozen=True)
class SubscribeAppCommand:
    tenant_id: str
    app_id: str


@dataclass(frozen=True)
class UnsubscribeAppCommand:
    tenant_id: str
    app_id: str


@dataclass(frozen=True)
class CreateRoleRequest:
    name: str
    capabilities: list[str]
    description: str | None = None


@dataclass(frozen=True)
class CreateRoleResponse:
    id: str
    name: str
    capabilities: list[str]


@dataclass(frozen=True)
class AssignUserRoleRequest:
    user_id: str
    role_id: str
