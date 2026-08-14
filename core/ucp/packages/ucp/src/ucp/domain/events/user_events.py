from ucp.domain.events.base import DomainEvent


class UserUpdatedEvent(DomainEvent):
    idp_user_id: str
    org_id: str
    first_name: str
    last_name: str
    role: str

    @property
    def event_name(self) -> str:
        return "UserUpdated"


class UserStatusToggledEvent(DomainEvent):
    idp_user_id: str
    org_id: str
    action: str

    @property
    def event_name(self) -> str:
        return "UserStatusToggled"


class UserDeletedEvent(DomainEvent):
    idp_user_id: str

    @property
    def event_name(self) -> str:
        return "UserDeleted"


class UserMembershipRemovedEvent(DomainEvent):
    idp_user_id: str
    org_id: str

    @property
    def event_name(self) -> str:
        return "UserMembershipRemoved"


class UserCreatedEvent(DomainEvent):
    org_id: str
    email: str
    first_name: str
    last_name: str
    role: str

    @property
    def event_name(self) -> str:
        return "UserInvited"
