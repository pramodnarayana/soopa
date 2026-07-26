from typing import Any

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.models.control_plane import (
    Tenant,
)
from sqlalchemy import select

from api.ports.tenant_repository import TenantRepositoryPort


class SqlAlchemyTenantRepository(TenantRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def get_tenant_flags(self, tenant_id: str) -> dict[str, Any] | None:
        result = await self.session.execute(select(Tenant).where(Tenant.id == tenant_id))
        tenant = result.scalar_one_or_none()
        if tenant:
            return {"allow_private_as2": tenant.allow_private_as2}
        return None
