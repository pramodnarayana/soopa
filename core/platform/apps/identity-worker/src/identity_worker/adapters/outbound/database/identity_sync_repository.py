from typing import Any, cast

from database.models.identity import Tenant as DbTenant
from database.models.identity import User as DbUser
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from identity_worker.ports.outbound.identity_sync_repository_port import (
    IdentitySyncRepositoryPort,
    IdentitySyncUnitOfWorkPort,
    SyncTenant,
    SyncUser,
)


class PostgresIdentitySyncRepository(IdentitySyncRepositoryPort):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_tenant(self, tenant_id: str) -> SyncTenant | None:
        stmt = select(DbTenant).where(DbTenant.id == tenant_id)
        result = await self.session.execute(stmt)
        tenant = result.scalar_one_or_none()
        if not tenant:
            return None
        return SyncTenant(id=tenant.id, idp_tenant_id=tenant.idp_tenant_id)

    async def get_user(self, user_id: str) -> SyncUser | None:
        stmt = select(DbUser).where(DbUser.id == user_id)
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            return None
        return SyncUser(id=user.id, idp_user_id=user.idp_user_id)

    async def get_user_for_update(self, user_id: str) -> SyncUser | None:
        stmt = select(DbUser).where(DbUser.id == user_id).with_for_update()
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        if not user:
            return None
        return SyncUser(id=user.id, idp_user_id=user.idp_user_id)

    async def update_user_idp_mapping(self, user_id: str, idp_user_id: str) -> None:
        stmt = update(DbUser).where(DbUser.id == user_id).values(idp_user_id=idp_user_id)
        await self.session.execute(stmt)


class PostgresIdentitySyncUnitOfWork:
    def __init__(self, session_factory: Any):
        self.session_factory = session_factory
        self.session: AsyncSession | None = None
        self.repo: IdentitySyncRepositoryPort = cast(IdentitySyncRepositoryPort, None)

    async def __aenter__(self) -> IdentitySyncUnitOfWorkPort:
        self._cm = self.session_factory()
        self.session = await self._cm.__aenter__()
        self.repo = PostgresIdentitySyncRepository(self.session)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self._cm.__aexit__(exc_type, exc_val, exc_tb)

    async def commit(self) -> None:
        if self.session:
            await self.session.commit()

    async def rollback(self) -> None:
        if self.session:
            await self.session.rollback()
