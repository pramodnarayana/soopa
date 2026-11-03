from typing import Protocol

from edi.domain.authorization.tenant import TenantFeatureFlags, TenantSummary


class TenantRepositoryPort(Protocol):
    """Port for retrieving tenant-level configuration globally."""

    async def get_tenant_flags(self, tenant_id: str) -> TenantFeatureFlags | None: ...

    async def get_tenant(self, tenant_id: str) -> TenantSummary | None: ...
