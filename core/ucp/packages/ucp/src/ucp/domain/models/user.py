from datetime import UTC, datetime
from typing import Literal

from ucp.domain.events.user_events import (
    UserDeletedEvent,
    UserMembershipRemovedEvent,
    UserStatusToggledEvent,
    UserUpdatedEvent,
)
from ucp.domain.models.aggregate_root import AggregateRoot


class User(AggregateRoot):
    ID_PREFIX = "usr"

    def __init__(
        self,
        id: str,
        idp_user_id: str | None,
        email: str,
        name: str,
        status: Literal["active", "inactive"],
        created_at: datetime,
        updated_at: datetime,
    ):
        super().__init__()
        self.id = id
        self.idp_user_id = idp_user_id
        self.email = email
        self.name = name
        self.status = status
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def create(
        cls,
        id: str,
        idp_user_id: str | None,
        email: str,
        name: str,
    ) -> "User":
        now = datetime.now(UTC)
        return cls(
            id=id,
            idp_user_id=idp_user_id,
            email=email,
            name=name,
            status="active",
            created_at=now,
            updated_at=now,
        )

    def set_idp_user_id(self, idp_user_id: str) -> None:
        if self.idp_user_id:
            raise ValueError(f"User already has an IDP mapping: {self.idp_user_id}")
        self.idp_user_id = idp_user_id
        self.updated_at = datetime.now(UTC)

    def activate(self) -> None:
        if self.status != "active":
            self.status = "active"
            self.updated_at = datetime.now(UTC)

    def deactivate(self) -> None:
        if self.status != "inactive":
            self.status = "inactive"
            self.updated_at = datetime.now(UTC)

    def update_profile(self, first_name: str, last_name: str, org_id: str, role: str) -> None:
        self.name = f"{first_name} {last_name}".strip()
        self.updated_at = datetime.now(UTC)
        if self.idp_user_id:
            self.add_domain_event(
                UserUpdatedEvent(
                    idp_user_id=self.idp_user_id,
                    org_id=org_id,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                )
            )

    def change_status(self, action: str, org_id: str) -> None:
        if action not in ("activate", "deactivate"):
            raise ValueError(f"Invalid action '{action}'. Must be 'activate' or 'deactivate'.")

        if action == "deactivate":
            self.deactivate()
        elif action == "activate":
            self.activate()

        if self.idp_user_id:
            self.add_domain_event(
                UserStatusToggledEvent(
                    idp_user_id=self.idp_user_id,
                    org_id=org_id,
                    action=action,
                )
            )

    def mark_deleted(self) -> None:
        if self.idp_user_id:
            self.add_domain_event(UserDeletedEvent(idp_user_id=self.idp_user_id))

    def remove_membership(self, org_id: str) -> None:
        """Remove user from an organization (IdP tenant).

        Args:
            org_id: The Identity Provider's organization/tenant ID, not the UCP tenant ID.
        """
        if self.idp_user_id:
            self.add_domain_event(
                UserMembershipRemovedEvent(idp_user_id=self.idp_user_id, org_id=org_id)
            )

    def assign_role(self, role_id: str) -> None:
        from ucp.domain.events.role_events import UserRoleAssignedEvent

        self.add_domain_event(UserRoleAssignedEvent(user_id=self.id, role_id=role_id))
