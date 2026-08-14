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


class ITenantQueryService(Protocol):
    """
    CQRS Read Service Port for Tenants.
    This service bypasses the Domain Model entirely to perform optimized read operations.
    """

    async def get_all_tenants(self) -> list[TenantReadModel]: ...

    async def get_tenant_by_id(self, tenant_id: str) -> TenantReadModel | None: ...

    async def get_tenant_by_slug(self, slug: str) -> TenantReadModel | None: ...
