from dataclasses import dataclass

from ucp.domain.events.base import DomainEvent


@dataclass(frozen=True)
class RoleCreatedEvent(DomainEvent):
    role_id: str
    name: str
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", tuple(self.capabilities))

    @property
    def event_name(self) -> str:
        return "role_created"

    def get_routing_tenant_id(self) -> str | None:
        return None  # Global event


@dataclass(frozen=True)
class UserRoleAssignedEvent(DomainEvent):
    user_id: str
    role_id: str
    role_name: str
    tenant_id: str | None
    idp_user_id: str | None

    @property
    def event_name(self) -> str:
        return "user_role_assigned"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
