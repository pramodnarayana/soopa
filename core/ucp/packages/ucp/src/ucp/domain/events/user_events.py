from dataclasses import dataclass

from ucp.domain.events.base import DomainEvent


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
        return None  # Global event


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
class UserCreatedEvent(DomainEvent):
    user_id: str
    tenant_id: str
    email: str
    first_name: str
    last_name: str
    role: str

    @property
    def event_name(self) -> str:
        return "UserInvited"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
