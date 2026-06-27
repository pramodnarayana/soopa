import contextlib

from database.connection import DatabaseRouter
from database.models import DatabaseShard, Tenant
from sqlalchemy import select


class TenantResolver:
    """
    Caches tenant-to-shard mapping to avoid querying the Global DB on every SQS message.
    """

    def __init__(self, db_router: DatabaseRouter):
        self.db_router = db_router
        self._cache: dict[int, tuple[str, str]] = {}

    async def resolve(self, tenant_id: int) -> tuple[str, str]:
        if tenant_id in self._cache:
            return self._cache[tenant_id]

        global_gen = self.db_router.get_global_session()
        global_session = await global_gen.__anext__()
        try:
            stmt = select(Tenant, DatabaseShard).join(DatabaseShard).where(Tenant.id == tenant_id)
            result = await global_session.execute(stmt)
            row = result.first()
            if not row:
                raise ValueError(f"Tenant {tenant_id} not found in Global DB")
            _, shard_obj = row
            self._cache[tenant_id] = (str(shard_obj.name), str(shard_obj.dsn))
            return self._cache[tenant_id]
        finally:
            with contextlib.suppress(StopAsyncIteration):
                await global_gen.__anext__()
