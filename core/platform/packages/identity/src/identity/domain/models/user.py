from datetime import UTC, datetime
from typing import Literal

from ucp.domain.events import (
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
        self.deleted_at: datetime | None = None
        self.role: str | None = None

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

    def update_profile(self, first_name: str, last_name: str, tenant_id: str, role: str) -> None:
        self.name = f"{first_name} {last_name}".strip()
        self.updated_at = datetime.now(UTC)
        if self.idp_user_id:
            self.add_domain_event(
                UserUpdatedEvent(
                    idp_user_id=self.idp_user_id,
                    tenant_id=tenant_id,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                )
            )

    def change_status(self, action: str, tenant_id: str) -> None:
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
                    tenant_id=tenant_id,
                    action=action,
                )
            )

    def mark_deleted(self) -> None:
        """Logically deletes this user.

        Sets deleted_at to signal soft deletion and emits UserDeletedEvent
        to cascade the deletion to the IdP user record asynchronously.
        No PII anonymization is applied at this stage — deferred to a future ticket.
        """
        if self.deleted_at is not None:
            raise ValueError(f"User '{self.id}' has already been deleted.")
        self.deleted_at = datetime.now(UTC)
        self.updated_at = self.deleted_at
        if self.idp_user_id:
            self.add_domain_event(UserDeletedEvent(idp_user_id=self.idp_user_id))

    def remove_membership(self, tenant_id: str) -> None:
        """Remove user from a UCP tenant.

        Args:
            tenant_id: The local UCP tenant ID.
        """
        if self.idp_user_id:
            self.add_domain_event(
                UserMembershipRemovedEvent(idp_user_id=self.idp_user_id, tenant_id=tenant_id)
            )

    def assign_role(self, role_id: str, role_name: str, tenant_id: str | None) -> None:
        from ucp.domain.events import UserRoleAssignedEvent

        self.add_domain_event(
            UserRoleAssignedEvent(
                user_id=self.id,
                role_id=role_id,
                role_name=role_name,
                tenant_id=tenant_id,
                idp_user_id=self.idp_user_id,
            )
        )
