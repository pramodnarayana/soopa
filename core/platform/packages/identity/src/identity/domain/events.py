from dataclasses import dataclass

from seedwork.events import DomainEvent

from identity.domain.constants import IdentityEventType


@dataclass(frozen=True)
class RoleCreatedEvent(DomainEvent):
    role_id: str
    name: str
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "capabilities", tuple(self.capabilities))

    @property
    def event_name(self) -> str:
        return IdentityEventType.ROLE_CREATED.value

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
        return IdentityEventType.USER_UPDATED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class UserStatusToggledEvent(DomainEvent):
    idp_user_id: str
    tenant_id: str
    action: str

    @property
    def event_name(self) -> str:
        return IdentityEventType.USER_STATUS_TOGGLED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class UserDeletedEvent(DomainEvent):
    idp_user_id: str

    @property
    def event_name(self) -> str:
        return IdentityEventType.USER_DELETED.value

    def get_routing_tenant_id(self) -> str | None:
        return None


@dataclass(frozen=True)
class UserMembershipRemovedEvent(DomainEvent):
    idp_user_id: str
    tenant_id: str

    @property
    def event_name(self) -> str:
        return IdentityEventType.USER_MEMBERSHIP_REMOVED.value

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
        return IdentityEventType.USER_ROLE_ASSIGNED.value

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
        return IdentityEventType.USER_INVITED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class UserTokensRevokedEvent(DomainEvent):
    user_id: str
    tokens_valid_after_iso: str
    reason: str

    @property
    def event_name(self) -> str:
        return IdentityEventType.USER_TOKENS_REVOKED.value

    def get_routing_tenant_id(self) -> str | None:
        return None


@dataclass(frozen=True)
class TenantTokensRevokedEvent(DomainEvent):
    tenant_id: str
    tokens_valid_after_iso: str
    reason: str

    @property
    def event_name(self) -> str:
        return IdentityEventType.TENANT_TOKENS_REVOKED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ResourceGrantUpdatedEvent(DomainEvent):
    grant_id: str
    tenant_id: str
    resource_type: str
    resource_id: str
    action: str

    @property
    def event_name(self) -> str:
        return IdentityEventType.RESOURCE_GRANT_UPDATED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class PolicyRuleUpdatedEvent(DomainEvent):
    policy_rule_id: str
    tenant_id: str
    action: str

    @property
    def event_name(self) -> str:
        return IdentityEventType.POLICY_RULE_UPDATED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class ExternalIdentityLinkedEvent(DomainEvent):
    user_id: str
    idp_issuer: str
    idp_subject: str

    @property
    def event_name(self) -> str:
        return IdentityEventType.EXTERNAL_IDENTITY_LINKED.value

    def get_routing_tenant_id(self) -> str | None:
        return None
