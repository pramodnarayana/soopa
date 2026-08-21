from typing import Protocol

from ucp.domain.models.tenant import Tenant


class TenantRepositoryPort(Protocol):
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

    async def delete(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        """Deletes a tenant and its related local infrastructure"""
        ...

    async def soft_delete_tenant_infrastructure(self, tenant_id: str) -> None:
        """Soft deletes all identities and infrastructure for a tenant (e.g. Webhooks, Roles, API Keys)"""
        ...

    async def allocate_shard(self, tenant_id: str, app_id: str, shard_id: str) -> None:
        """Allocates a database shard for a tenant's application subscription"""
        ...

    async def upsert_app_subscription(self, tenant_id: str, app_id: str, status: str) -> None:
        """Upserts an application subscription status for a tenant"""
        ...
