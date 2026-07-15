from typing import Protocol


class TenantPort(Protocol):
    async def get_all_tenant_ids(self) -> list[int]:
        """Fetch all active tenant IDs from the Global DB."""
        ...

    async def resolve_shard(self, tenant_id: int) -> tuple[str, str]:
        """Resolve a tenant_id to a database shard (name, dsn)."""
        ...
