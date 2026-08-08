from typing import Any, Protocol


class TenantRepositoryPort(Protocol):
    """
    Port for retrieving tenant-level configuration globally.
    """

    async def get_tenant_flags(self, tenant_id: str) -> dict[str, Any] | None: ...

    async def get_tenant(self, tenant_id: str) -> dict[str, Any] | None: ...
