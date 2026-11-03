from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.exceptions import Result

from identity.domain.constants import IdentityIdPrefix, UserStatus, UserStatusAction
from identity.domain.events import (
    UserCreatedEvent,
    UserDeletedEvent,
    UserMembershipRemovedEvent,
    UserRoleAssignedEvent,
    UserStatusToggledEvent,
    UserUpdatedEvent,
)
from identity.domain.exceptions import IdentityError, IdentityErrorCode


@dataclass(eq=False)
class User(AggregateRoot):
    ID_PREFIX: ClassVar[str] = IdentityIdPrefix.USER.value

    id: str
    idp_user_id: str | None
    email: str
    name: str
    status: UserStatus = UserStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None
    role: str | None = None

    @classmethod
    def create(
        cls,
        id: str | None = None,
        idp_user_id: str | None = None,
        *,
        email: str,
        name: str,
    ) -> Result[User, IdentityError]:
        cleaned_email = email.strip()
        cleaned_name = name.strip()
        if not cleaned_email or "@" not in cleaned_email or not cleaned_name:
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.VALIDATION_FAILED,
                    message="User email must be valid and name cannot be empty.",
                )
            )
        now = datetime.now(UTC)
        return Result.ok(
            cls(
                id=id or cls.new_id(),
                idp_user_id=idp_user_id,
                email=cleaned_email,
                name=cleaned_name,
                status=UserStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
        )

    def record_invitation(
        self,
        *,
        tenant_id: str,
        first_name: str,
        last_name: str,
        role: str,
    ) -> None:
        """Records UserCreatedEvent to provision and invite this user in the IdP."""
        self.add_domain_event(
            UserCreatedEvent(
                user_id=self.id,
                tenant_id=tenant_id,
                email=self.email,
                first_name=first_name,
                last_name=last_name,
                role=role,
            )
        )

    def set_idp_user_id(self, idp_user_id: str) -> Result[User, IdentityError]:
        if self.idp_user_id:
            if self.idp_user_id == idp_user_id:
                return Result.ok(self)
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.IDP_MAPPING_CONFLICT,
                    message=f"User already has an IDP mapping: {self.idp_user_id}",
                )
            )
        self.idp_user_id = idp_user_id
        self.updated_at = datetime.now(UTC)
        return Result.ok(self)

    def activate(self) -> None:
        if self.status != UserStatus.ACTIVE:
            self.status = UserStatus.ACTIVE
            self.updated_at = datetime.now(UTC)

    def deactivate(self) -> None:
        if self.status != UserStatus.INACTIVE:
            self.status = UserStatus.INACTIVE
            self.updated_at = datetime.now(UTC)

    def update_profile(
        self, first_name: str, last_name: str, tenant_id: str, role: str
    ) -> Result[User, IdentityError]:
        cleaned_first = first_name.strip()
        cleaned_last = last_name.strip()
        full_name = f"{cleaned_first} {cleaned_last}".strip()
        if not full_name:
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.VALIDATION_FAILED,
                    message="User profile name cannot be blank.",
                )
            )
        self.name = full_name
        self.updated_at = datetime.now(UTC)
        if self.idp_user_id:
            self.add_domain_event(
                UserUpdatedEvent(
                    idp_user_id=self.idp_user_id,
                    tenant_id=tenant_id,
                    first_name=cleaned_first,
                    last_name=cleaned_last,
                    role=role,
                )
            )
        return Result.ok(self)

    def change_status(
        self, action: UserStatusAction, tenant_id: str
    ) -> Result[User, IdentityError]:
        if action is UserStatusAction.DEACTIVATE:
            self.deactivate()
        else:
            self.activate()

        if self.idp_user_id:
            self.add_domain_event(
                UserStatusToggledEvent(
                    idp_user_id=self.idp_user_id,
                    tenant_id=tenant_id,
                    action=action.value,
                )
            )
        return Result.ok(self)

    def mark_deleted(self) -> Result[User, IdentityError]:
        """Logically deletes this user and emits UserDeletedEvent if mapped in the IdP."""
        if self.deleted_at is not None:
            return Result.fail(
                IdentityError(
                    code=IdentityErrorCode.USER_ALREADY_DELETED,
                    message=f"User '{self.id}' has already been deleted.",
                )
            )
        self.deleted_at = datetime.now(UTC)
        self.updated_at = self.deleted_at
        if self.idp_user_id:
            self.add_domain_event(UserDeletedEvent(idp_user_id=self.idp_user_id))
        return Result.ok(self)

    def remove_membership(self, tenant_id: str) -> None:
        """Remove user from a UCP tenant."""
        if self.idp_user_id:
            self.add_domain_event(
                UserMembershipRemovedEvent(idp_user_id=self.idp_user_id, tenant_id=tenant_id)
            )

    def assign_role(self, role_id: str, role_name: str, tenant_id: str | None) -> None:
        self.add_domain_event(
            UserRoleAssignedEvent(
                user_id=self.id,
                role_id=role_id,
                role_name=role_name,
                tenant_id=tenant_id,
                idp_user_id=self.idp_user_id,
            )
        )
