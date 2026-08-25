from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DomainEvent(ABC):
    """
    Marker base class for all domain events.

    Events are immutable dataclasses serialized for the Outbox pattern by the
    shared domain-event serializer.
    """

    @property
    @abstractmethod
    def event_name(self) -> str:
        """Returns the canonical event name for messaging (e.g. 'tenant.provisioned')."""
        raise NotImplementedError

    @abstractmethod
    def get_routing_tenant_id(self) -> str | None:
        """
        Returns the tenant ID associated with this event for Outbox routing.
        If the event is platform-wide and has no tenant context, return None.
        """
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


@dataclass(frozen=True)
class TenantProvisionedEvent(DomainEvent):
    tenant_id: str
    tenant_name: str
    subscriptions: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "subscriptions", tuple(self.subscriptions))

    @property
    def event_name(self) -> str:
        return "tenant.provisioned"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class AppSubscribedEvent(DomainEvent):
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return "app.subscribed"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class AppUnsubscribedEvent(DomainEvent):
    tenant_id: str
    app_id: str

    @property
    def event_name(self) -> str:
        return "app.unsubscribed"

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class TenantNameUpdatedEvent(DomainEvent):
    org_id: str
    name: str

    @property
    def event_name(self) -> str:
        return "TenantNameUpdated"

    def get_routing_tenant_id(self) -> str | None:
        return self.org_id


@dataclass(frozen=True)
class TenantStatusToggledEvent(DomainEvent):
    org_id: str
    active: bool

    @property
    def event_name(self) -> str:
        return "TenantStatusToggled"

    def get_routing_tenant_id(self) -> str | None:
        return self.org_id


@dataclass(frozen=True)
class TenantDeletedEvent(DomainEvent):
    org_id: str

    @property
    def event_name(self) -> str:
        return "TenantDeleted"

    def get_routing_tenant_id(self) -> str | None:
        return self.org_id


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


@dataclass(frozen=True)
class WebhookCreatedEvent(DomainEvent):
    """
    Emitted when a new Webhook is created.
    """

    tenant_id: str
    webhook_id: str
    event_type: str = "webhook.created"

    @property
    def event_name(self) -> str:
        return self.event_type

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "webhook_id": self.webhook_id,
            "event_type": self.event_type,
        }


@dataclass(frozen=True)
class WebhookUpdatedEvent(DomainEvent):
    """
    Emitted when a Webhook is updated.
    """

    tenant_id: str
    webhook_id: str
    event_type: str = "webhook.updated"

    @property
    def event_name(self) -> str:
        return self.event_type

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "webhook_id": self.webhook_id,
            "event_type": self.event_type,
        }


@dataclass(frozen=True)
class WebhookDeletedEvent(DomainEvent):
    """
    Emitted when a Webhook is deleted.
    """

    tenant_id: str
    webhook_id: str
    event_type: str = "webhook.deleted"

    @property
    def event_name(self) -> str:
        return self.event_type

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "webhook_id": self.webhook_id,
            "event_type": self.event_type,
        }
