from typing import Protocol


class ReplicationPort(Protocol):
    async def replicate_tenant_configuration(self, tenant_id: int) -> None:
        """Copy all relevant configuration from Global DB to Tenant DB Shard."""
        ...
