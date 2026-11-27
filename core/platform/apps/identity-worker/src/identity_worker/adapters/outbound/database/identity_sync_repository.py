from database.models.identity import ExternalIdentity as DbExternalIdentity
from database.models.identity import Tenant as DbTenant
from database.models.identity import User as DbUser
from seedwork.utils import generate_id
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
        return SyncTenant(
            id=tenant.id,
            name=tenant.name,
            idp_realm_name=tenant.idp_realm_name,
            slug=tenant.slug,
            isolation_mode=tenant.isolation_mode,
        )

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

    async def update_tenant_idp_realm(self, tenant_id: str, idp_realm_name: str) -> None:
        stmt = (
            update(DbTenant).where(DbTenant.id == tenant_id).values(idp_realm_name=idp_realm_name)
        )
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

    async def upsert_external_identity(
        self,
        *,
        user_id: str,
        idp_issuer: str,
        idp_subject: str,
        idp_realm_name: str | None = None,
    ) -> None:
        normalized_issuer = idp_issuer.strip().rstrip("/")
        stmt = select(DbExternalIdentity).where(
            DbExternalIdentity.idp_issuer == normalized_issuer,
            DbExternalIdentity.idp_subject == idp_subject,
        )
        result = await self.session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.user_id = user_id
            if idp_realm_name:
                existing.idp_realm_name = idp_realm_name
            await self.session.flush()
            return

        self.session.add(
            DbExternalIdentity(
                id=generate_id("iam_ext"),
                user_id=user_id,
                idp_issuer=normalized_issuer,
                idp_subject=idp_subject,
                idp_realm_name=idp_realm_name,
            )
        )
        await self.session.flush()

    async def find_external_identity_realm(self, idp_subject: str) -> str | None:
        stmt = (
            select(DbExternalIdentity.idp_realm_name)
            .where(DbExternalIdentity.idp_subject == idp_subject)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
