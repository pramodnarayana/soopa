from database.models.identity import Tenant as DbTenant
from database.models.identity import User as DbUser
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from identity_worker.ports.outbound.identity_sync_repository_port import (
    IdentitySyncRepositoryPort,
    SyncTenant,
    SyncUser,
)


class SqlAlchemyIdentitySyncRepository(IdentitySyncRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def _to_sync_tenant(tenant: DbTenant) -> SyncTenant:
        return SyncTenant(id=tenant.id, name=tenant.name, idp_tenant_id=tenant.idp_tenant_id)

    @staticmethod
    def _to_sync_user(user: DbUser) -> SyncUser:
        return SyncUser(id=user.id, idp_user_id=user.idp_user_id)

    async def get_tenant(self, tenant_id: str) -> SyncTenant | None:
        stmt = select(DbTenant).where(DbTenant.id == tenant_id)
        result = await self.session.execute(stmt)
        tenant = result.scalar_one_or_none()
        if not tenant:
            return None
        return self._to_sync_tenant(tenant)

    async def update_tenant_idp_mapping(self, tenant_id: str, idp_tenant_id: str) -> None:
        stmt = update(DbTenant).where(DbTenant.id == tenant_id).values(idp_tenant_id=idp_tenant_id)
        await self.session.execute(stmt)

    async def get_user(self, user_id: str) -> SyncUser | None:
        stmt = select(DbUser).where(DbUser.id == user_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            return None
        return self._to_sync_user(user)

    async def get_user_for_update(self, user_id: str) -> SyncUser | None:
        stmt = select(DbUser).where(DbUser.id == user_id).with_for_update()
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            return None
        return self._to_sync_user(user)

    async def update_user_idp_mapping(self, user_id: str, idp_user_id: str) -> None:
        stmt = update(DbUser).where(DbUser.id == user_id).values(idp_user_id=idp_user_id)
        await self.session.execute(stmt)
