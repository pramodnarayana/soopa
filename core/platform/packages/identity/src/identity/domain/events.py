from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DomainEvent(ABC):
    @property
    @abstractmethod
    def event_name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_routing_tenant_id(self) -> str | None:
        raise NotImplementedError


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
        return None


@dataclass(frozen=True)
class UserUpdatedEvent(DomainEvent):
    idp_user_id: str
    tenant_id: str
    first_name: str
    last_name: str
    role: str

    @property
    def event_name(self) -> str:
        return "UserUpdated"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class UserStatusToggledEvent(DomainEvent):
    idp_user_id: str
    tenant_id: str
    action: str

    @property
    def event_name(self) -> str:
        return "UserStatusToggled"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class UserDeletedEvent(DomainEvent):
    idp_user_id: str

    @property
    def event_name(self) -> str:
        return "UserDeleted"

    def get_routing_tenant_id(self) -> str | None:
        return None


@dataclass(frozen=True)
class UserMembershipRemovedEvent(DomainEvent):
    idp_user_id: str
    tenant_id: str

    @property
    def event_name(self) -> str:
        return "UserMembershipRemoved"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


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
