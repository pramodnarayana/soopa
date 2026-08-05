from typing import Protocol

from ucp_api.domain.models.tenant import Tenant


class ITenantRepository(Protocol):
    async def save(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        """Saves a tenant and its domain events to the database within a transaction"""
        ...

    async def find_by_id(self, id: str) -> Tenant | None:
        """Finds a tenant by ID"""
        ...

    async def find_by_idp_tenant_id(self, idp_tenant_id: str) -> Tenant | None:
        """Finds a tenant by its IDP Tenant ID (e.g. Zitadel Org ID)"""
        ...

    async def find_all(self) -> list[Tenant]:
        """Returns all tenants"""
        ...

    async def delete(self, tenant_id: str, idempotency_key: str | None = None) -> None:
        """Deletes a tenant and its related local infrastructure"""
        ...
