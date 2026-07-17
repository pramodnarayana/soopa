from database.connection import DatabaseRouter
from database.models.control_plane import DatabaseShard, Tenant
from sqlalchemy import select


class TenantResolver:
    """
    Caches tenant-to-shard mapping to avoid querying the Global DB on every SQS message.
    """

    def __init__(self, db_router: DatabaseRouter, ttl_secs: int = 300, max_entries: int = 1000):
        self.db_router = db_router
        self._cache: dict[int, tuple[str, str, float]] = {}
        self._ttl = ttl_secs
        self._max_entries = max_entries

    def _sweep(self, now: float) -> None:
        expired = [k for k, v in self._cache.items() if v[2] <= now]
        for k in expired:
            del self._cache[k]

        if len(self._cache) > self._max_entries:
            sorted_entries = sorted(self._cache.items(), key=lambda x: x[1][2])
            to_evict = len(self._cache) - self._max_entries
            for k, _ in sorted_entries[:to_evict]:
                del self._cache[k]

    async def resolve(self, tenant_id: int) -> tuple[str, str]:
        import time

        now = time.time()
        self._sweep(now)

        if tenant_id in self._cache:
            shard_name, shard_dsn, expiry = self._cache[tenant_id]
            if now < expiry:
                return shard_name, shard_dsn

        global_gen = self.db_router.get_global_session()
        global_session = await global_gen.__anext__()
        try:
            stmt = select(Tenant, DatabaseShard).join(DatabaseShard).where(Tenant.id == tenant_id)
            result = await global_session.execute(stmt)
            row = result.first()
            if not row:
                raise ValueError(f"Tenant {tenant_id} not found in Global DB")
            _, shard_obj = row
            self._cache[tenant_id] = (str(shard_obj.name), str(shard_obj.dsn), now + self._ttl)
            self._sweep(now)
            return str(shard_obj.name), str(shard_obj.dsn)
        finally:
            await global_gen.aclose()
