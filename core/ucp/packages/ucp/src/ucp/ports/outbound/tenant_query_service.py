from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol


@dataclass(frozen=True)
class TenantReadModel:
    id: str
    name: str
    slug: str
    idp_tenant_id: str | None
    status: Literal["active", "inactive"]
    subscriptions: list[str]  # List of application slugs
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class PaginatedTenants:
    items: list[TenantReadModel]
    total: int
    page: int
    limit: int


class ITenantQueryService(Protocol):
    """
    CQRS Read Service Port for Tenants.
    This service bypasses the Domain Model entirely to perform optimized read operations.

    Stable tenant sort order: ORDER BY id ASC for deterministic pagination.
    """

    async def get_all_tenants(self, page: int = 1, limit: int = 50) -> PaginatedTenants: ...

    async def get_tenant_by_id(self, tenant_id: str) -> TenantReadModel | None: ...

    async def get_tenant_by_slug(self, slug: str) -> TenantReadModel | None: ...
