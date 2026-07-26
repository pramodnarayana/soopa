from typing import Protocol


class TenantPort(Protocol):
    async def get_all_tenant_ids(self) -> list[str]:
        """Fetch all active tenant IDs from the Global DB."""
        ...

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        """Resolve a tenant_id to a database shard (name, dsn)."""
        ...

    async def upsert_tenant(self, tenant_id: str, name: str) -> None:
        """Upsert a tenant into the global database."""
        ...
