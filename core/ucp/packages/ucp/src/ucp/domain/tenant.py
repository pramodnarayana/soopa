"""Tenant Behavioral Aggregate Root for the UCP Bounded Context."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from identity.domain.constants import TenantIsolationMode
from seedwork.domain.aggregate import AggregateRoot
from seedwork.domain.exceptions import Result

from ucp.domain.constants import LifecycleStatus, UcpIdPrefix
from ucp.domain.events import (
    AppSubscribedEvent,
    AppUnsubscribedEvent,
    TenantDeletedEvent,
    TenantNameUpdatedEvent,
    TenantProvisionedEvent,
    TenantStatusToggledEvent,
)
from ucp.domain.exceptions import (
    AppAlreadySubscribedError,
    AppNotSubscribedError,
    EmptyTenantNameError,
    IdpOrganizationConflictError,
    InvalidTenantSlugError,
    TenantAlreadyDeletedError,
    TenantInactiveForSubscriptionError,
    UcpError,
)

__all__ = ["Tenant", "TenantSubscription"]


@dataclass
class TenantSubscription:
    app_id: str
    status: LifecycleStatus


@dataclass(eq=False)
class Tenant(AggregateRoot):
    """Aggregate Root governing Tenant lifecycle, IdP organization binding, and app subscriptions."""

    ID_PREFIX: ClassVar[str] = UcpIdPrefix.TENANT.value

    id: str
    name: str
    slug: str
    idp_realm_name: str | None
    status: LifecycleStatus
    created_at: datetime
    updated_at: datetime
    isolation_mode: TenantIsolationMode = TenantIsolationMode.POOLED_REALM
    subscriptions: list[TenantSubscription] = field(default_factory=list)
    deleted_at: datetime | None = None

    @classmethod
    def create(
        cls,
        id: str,
        name: str,
        slug: str,
        idp_realm_name: str | None = None,
        isolation_mode: TenantIsolationMode = TenantIsolationMode.POOLED_REALM,
        subscriptions: list[TenantSubscription] | None = None,
    ) -> Result[Tenant, UcpError]:
        if not name or not name.strip():
            return Result.fail(EmptyTenantNameError())
        if not slug or not slug.strip():
            return Result.fail(InvalidTenantSlugError.for_name(name))

        now = datetime.now(UTC)
        cleaned_name = name.strip()
        cleaned_slug = slug.strip()
        resolved_subs = list(subscriptions) if subscriptions is not None else []

        tenant = cls(
            id=id or cls.new_id(),
            name=cleaned_name,
            slug=cleaned_slug,
            idp_realm_name=idp_realm_name,
            isolation_mode=isolation_mode,
            status=LifecycleStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            subscriptions=resolved_subs,
        )
        tenant.add_domain_event(
            TenantProvisionedEvent(
                tenant_id=tenant.id,
                tenant_name=tenant.name,
                subscriptions=tuple(
                    s.app_id for s in tenant.subscriptions if s.status == LifecycleStatus.ACTIVE
                ),
            )
        )
        return Result.ok(tenant)

    def _dedicated_idp_realm(self) -> str | None:
        if self.isolation_mode == TenantIsolationMode.DEDICATED_IDP_ORG:
            return self.idp_realm_name
        return None

    def rename(self, new_name: str) -> Result[Tenant, UcpError]:
        if not new_name or not new_name.strip():
            return Result.fail(EmptyTenantNameError())
        cleaned = new_name.strip()
        if cleaned == self.name:
            return Result.ok(self)

        self.name = cleaned
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            TenantNameUpdatedEvent(
                tenant_id=self.id,
                name=self.name,
                idp_realm_name=self._dedicated_idp_realm(),
            )
        )
        return Result.ok(self)

    def set_idp_realm_name(self, idp_realm_name: str) -> Result[Tenant, UcpError]:
        if self.idp_realm_name:
            if self.idp_realm_name == idp_realm_name:
                return Result.ok(self)
            return Result.fail(IdpOrganizationConflictError.for_realm(self.idp_realm_name))
        self.idp_realm_name = idp_realm_name
        self.updated_at = datetime.now(UTC)
        return Result.ok(self)

    def subscribe(self, app_id: str, idp_project_id: str | None = None) -> Result[Tenant, UcpError]:
        if self.status != LifecycleStatus.ACTIVE:
            return Result.fail(TenantInactiveForSubscriptionError())

        sub = next((s for s in self.subscriptions if s.app_id == app_id), None)
        if sub:
            if sub.status == LifecycleStatus.ACTIVE:
                return Result.fail(AppAlreadySubscribedError.for_app(app_id))
            sub.status = LifecycleStatus.ACTIVE
        else:
            self.subscriptions.append(
                TenantSubscription(app_id=app_id, status=LifecycleStatus.ACTIVE)
            )

        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            AppSubscribedEvent(tenant_id=self.id, app_id=app_id, idp_project_id=idp_project_id)
        )
        return Result.ok(self)

    def unsubscribe_from_app(
        self, app_id: str, idp_project_id: str | None = None
    ) -> Result[Tenant, UcpError]:
        sub = next((s for s in self.subscriptions if s.app_id == app_id), None)
        if not sub or sub.status == LifecycleStatus.INACTIVE:
            return Result.fail(AppNotSubscribedError.for_app(app_id))

        sub.status = LifecycleStatus.INACTIVE
        self.updated_at = datetime.now(UTC)
        self.add_domain_event(
            AppUnsubscribedEvent(tenant_id=self.id, app_id=app_id, idp_project_id=idp_project_id)
        )
        return Result.ok(self)

    def change_status(self, new_status: LifecycleStatus) -> Result[Tenant, UcpError]:
        if self.status != new_status:
            self.status = new_status
            self.updated_at = datetime.now(UTC)
            self.add_domain_event(
                TenantStatusToggledEvent(
                    tenant_id=self.id,
                    active=self.status == LifecycleStatus.ACTIVE,
                    idp_realm_name=self._dedicated_idp_realm(),
                )
            )
        return Result.ok(self)

    def mark_deleted(self) -> Result[Tenant, UcpError]:
        """Logically deletes this tenant and stages TenantDeletedEvent for async cascade cleanup."""
        if self.deleted_at is not None:
            return Result.fail(TenantAlreadyDeletedError.for_id(self.id))
        self.deleted_at = datetime.now(UTC)
        self.updated_at = self.deleted_at
        self.add_domain_event(
            TenantDeletedEvent(
                tenant_id=self.id,
                idp_realm_name=self._dedicated_idp_realm(),
            )
        )
        return Result.ok(self)
