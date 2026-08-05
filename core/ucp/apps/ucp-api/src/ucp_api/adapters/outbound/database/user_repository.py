from datetime import UTC

from platform_orm.models.identity import TenantUser
from platform_orm.models.identity import User as DbUser
from sqlalchemy import and_, delete, exists, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ucp_api.domain.models.user import User
from ucp_api.ports.outbound.user_repository import IUserRepository


class UserRepository(IUserRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_users_by_tenant(self, tenant_id: str) -> list[User]:
        stmt = (
            select(DbUser, TenantUser.role)
            .join(TenantUser, TenantUser.user_id == DbUser.id)
            .where(TenantUser.tenant_id == tenant_id)
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        users = []
        for db_user, role in rows:
            u = User(
                id=db_user.id,
                idp_user_id=db_user.idp_user_id,
                email=db_user.email,
                name=db_user.name or "",
                status=db_user.status,
                created_at=db_user.created_at.replace(tzinfo=UTC),
                updated_at=db_user.updated_at.replace(tzinfo=UTC),
            )
            u.role = role  # type: ignore
            users.append(u)
        return users

    async def delete_orphaned_users(self, user_ids: list[str]) -> None:
        if not user_ids:
            return

        stmt = delete(DbUser).where(
            and_(DbUser.id.in_(user_ids), not_(exists().where(TenantUser.user_id == DbUser.id)))
        )
        await self.session.execute(stmt)

    async def save(self, user: User) -> None:
        stmt = select(DbUser).where(DbUser.id == user.id)
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if db_user:
            db_user.email = user.email
            db_user.name = user.name
            db_user.idp_user_id = user.idp_user_id
            db_user.status = user.status
        else:
            db_user = DbUser(
                id=user.id,
                idp_user_id=user.idp_user_id,
                email=user.email,
                name=user.name,
                created_at=user.created_at.replace(tzinfo=None),
            )
            self.session.add(db_user)

    async def save_tenant_membership(self, tenant_id: str, user_id: str, role: str) -> None:
        stmt = select(TenantUser).where(
            and_(TenantUser.tenant_id == tenant_id, TenantUser.user_id == user_id)
        )
        result = await self.session.execute(stmt)
        tenant_user = result.scalar_one_or_none()

        if tenant_user:
            tenant_user.role = role
        else:
            tenant_user = TenantUser(tenant_id=tenant_id, user_id=user_id, role=role)
            self.session.add(tenant_user)

    async def remove_tenant_membership(self, tenant_id: str, user_id: str) -> None:
        stmt = delete(TenantUser).where(
            and_(TenantUser.tenant_id == tenant_id, TenantUser.user_id == user_id)
        )
        await self.session.execute(stmt)

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        """Check if a user has any remaining tenant memberships."""
        stmt = select(TenantUser).where(TenantUser.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.first() is not None
