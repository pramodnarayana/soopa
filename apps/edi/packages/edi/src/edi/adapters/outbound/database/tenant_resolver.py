import time

from platform_orm.models.identity import Tenant
from sqlalchemy import select
from ucp_models.infrastructure import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

from edi.adapters.outbound.database.connection import DatabaseRouter

EDI_APP_SLUG = "edi"


class TenantResolver:
    """
    Caches tenant-to-shard mapping to avoid querying the Global DB on every SQS message.
    """

    def __init__(self, db_router: DatabaseRouter, ttl_secs: int = 300, max_entries: int = 1000):
        self.db_router = db_router
        self._cache: dict[str, tuple[str, str, float]] = {}
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

    async def resolve(self, tenant_id: str) -> tuple[str, str]:
        now = time.monotonic()
        self._sweep(now)

        tid_str = tenant_id
        if tid_str in self._cache:
            shard_name, shard_dsn, expiry = self._cache[tid_str]
            if now < expiry:
                return shard_name, shard_dsn

        global_gen = self.db_router.get_global_session()
        global_session = await global_gen.__anext__()
        try:
            stmt = (
                select(Tenant, DatabaseShard)
                .join(ShardRegistry, Tenant.id == ShardRegistry.tenant_id)
                .join(DatabaseShard, ShardRegistry.shard_id == DatabaseShard.id)
                .join(App, App.id == ShardRegistry.app_id)
                .where(Tenant.id == tid_str, App.slug == EDI_APP_SLUG)
            )
            result = await global_session.execute(stmt)
            row = result.first()
            if not row:
                raise ValueError(f"Tenant {tid_str} not found in Global DB")
            _, shard_obj = row
            self._cache[tid_str] = (str(shard_obj.name), str(shard_obj.dsn), now + self._ttl)
            self._sweep(now)
            return str(shard_obj.name), str(shard_obj.dsn)
        finally:
            await global_gen.aclose()
