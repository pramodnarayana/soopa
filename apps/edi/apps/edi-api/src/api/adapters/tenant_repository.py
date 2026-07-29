from typing import Any

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.models.control_plane import (
    Tenant,
    TenantShard,
)
from sqlalchemy import select

from api.ports.tenant_repository import TenantRepositoryPort


class SqlAlchemyTenantRepository(TenantRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def get_tenant_flags(self, tenant_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if not tenant:
            return None

        # Fetch the tenant shard configuration to get the allow_private_as2 flag
        shard_result = await self.session.execute(
            select(TenantShard).where(TenantShard.tenant_id == tenant_id)
        )
        tenant_shard = shard_result.scalar_one_or_none()

        return {"allow_private_as2": tenant_shard.allow_private_as2 if tenant_shard else False}
