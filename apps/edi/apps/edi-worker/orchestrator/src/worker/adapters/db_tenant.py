import contextlib

from database.connection import DatabaseRouter
from database.models import DatabaseShard, Tenant, TenantShard
from sqlalchemy import select

from worker.ports.tenant import TenantPort


class SqlAlchemyTenantAdapter(TenantPort):
    def __init__(self, db_router: DatabaseRouter):
        self.db_router = db_router
        self._cache: dict[str, tuple[str, str]] = {}

    async def get_all_tenant_ids(self) -> list[str]:
        global_gen = self.db_router.get_global_session()
        global_session = await global_gen.__anext__()
        try:
            stmt = select(Tenant.id).join(TenantShard).join(DatabaseShard)
            result = await global_session.execute(stmt)
            return [str(t_id) for t_id in result.scalars().all()]
        finally:
            with contextlib.suppress(StopAsyncIteration):
                await global_gen.__anext__()

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        if tenant_id in self._cache:
            return self._cache[tenant_id]

        global_gen = self.db_router.get_global_session()
        global_session = await global_gen.__anext__()
        try:
            stmt = (
                select(Tenant, DatabaseShard)
                .join(TenantShard, Tenant.id == TenantShard.tenant_id)
                .join(DatabaseShard, TenantShard.shard_id == DatabaseShard.id)
                .where(Tenant.id == tenant_id)
            )
            result = await global_session.execute(stmt)
            row = result.first()
            if not row:
                raise ValueError(f"Tenant {tenant_id} not found or mapped to a shard in Global DB")
            _, shard_obj = row
            self._cache[tenant_id] = (str(shard_obj.name), str(shard_obj.dsn))
            return self._cache[tenant_id]
        finally:
            with contextlib.suppress(StopAsyncIteration):
                await global_gen.__anext__()
