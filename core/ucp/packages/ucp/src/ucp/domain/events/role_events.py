from ucp.domain.events.base import DomainEvent


class RoleCreatedEvent(DomainEvent):
    role_id: str
    name: str
    capabilities: list[str]

    @property
    def event_name(self) -> str:
        return "role_created"


class UserRoleAssignedEvent(DomainEvent):
    user_id: str
    role_id: str

    @property
    def event_name(self) -> str:
        return "user_role_assigned"
