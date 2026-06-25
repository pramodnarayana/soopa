import logging

from database.models import DatabaseShard, Tenant, TenantUser, User
from identity.application.ports import IIdentityRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class SQLAlchemyIdentityRepository(IIdentityRepository):
    """
    SQLAlchemy Adapter for the IIdentityRepository port.
    Manages all direct database interactions for identity resolution and JIT provisioning.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_id_by_email(self, email: str) -> int | None:
        stmt = select(User).where(User.email == email)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(user.id) if user else None

    async def get_tenant_id_for_user(self, user_id: int) -> int | None:
        stmt = select(TenantUser).where(TenantUser.user_id == user_id)
        tenant_user = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(tenant_user.tenant_id) if tenant_user else None

    async def provision_tenant_for_user(self, email: str, name: str) -> int:
        logger.info(f"User {email} not found. Initiating JIT provisioning.")

        # Find default shard
        shard_stmt = select(DatabaseShard).where(DatabaseShard.name == "edi_shard_1")
        shard = (await self.session.execute(shard_stmt)).scalar_one_or_none()
        if not shard:
            raise RuntimeError("Default shard not found for provisioning")

        # 1. Create User
        user = User(email=email, name=name or str(email).split("@")[0])
        self.session.add(user)
        await self.session.flush()

        # 2. Create Tenant
        tenant = Tenant(name=f"{user.name}'s Organization", shard_id=int(shard.id))
        self.session.add(tenant)
        await self.session.flush()

        # 3. Create TenantUser map
        tenant_user = TenantUser(tenant_id=int(tenant.id), user_id=int(user.id), role="admin")
        self.session.add(tenant_user)

        await self.session.commit()
        logger.info(f"JIT Provisioned new tenant {tenant.name} for user {email}")
        return int(tenant.id)
