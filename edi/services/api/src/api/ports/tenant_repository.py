from typing import Any, Protocol


class TenantRepositoryPort(Protocol):
    """
    Port for retrieving tenant-level configuration globally.
    """

    async def get_tenant_flags(self, tenant_id: int) -> dict[str, Any] | None: ...
