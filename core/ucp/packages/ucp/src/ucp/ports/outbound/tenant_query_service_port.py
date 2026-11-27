from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from identity.domain.constants import TenantIsolationMode

from ucp.domain.constants import LifecycleStatus


@dataclass(frozen=True)
class TenantReadModel:
    id: str
    name: str
    slug: str
    idp_realm_name: str | None
    status: Literal[LifecycleStatus.ACTIVE, LifecycleStatus.INACTIVE]
    subscriptions: list[str]  # List of application slugs
    created_at: datetime
    updated_at: datetime
    isolation_mode: TenantIsolationMode = TenantIsolationMode.POOLED_REALM


@dataclass(frozen=True)
class PaginatedTenants:
    items: list[TenantReadModel]
    total: int
    page: int
    limit: int


class TenantQueryServicePort(Protocol):
    """
    CQRS Read Service Port for Tenants.
    This service bypasses the Domain Model entirely to perform optimized read operations.

    Stable tenant sort order: ORDER BY id ASC for deterministic pagination.
    """

    async def get_all_tenants(self, page: int = 1, limit: int = 50) -> PaginatedTenants: ...

    async def get_tenant_by_id(self, tenant_id: str) -> TenantReadModel | None: ...

    async def get_tenant_by_slug(self, slug: str) -> TenantReadModel | None: ...
