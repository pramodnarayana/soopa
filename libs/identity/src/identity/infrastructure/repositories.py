import logging

from database.models import DatabaseShard, Tenant, TenantUser, User
from identity.application.ports import IIdentityRepository
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)


class SQLAlchemyIdentityRepository(IIdentityRepository):
    """
    SQLAlchemy Adapter for the IIdentityRepository port.
    Manages all direct database interactions for identity resolution and JIT provisioning.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_user_id_by_email(self, email: str) -> int | None:
        stmt = select(User).where(func.lower(User.email) == email.lower())
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(user.id) if user else None

    async def get_tenant_id_for_user(self, user_id: int) -> int | None:
        stmt = select(TenantUser).where(TenantUser.user_id == user_id)
        tenant_user = (await self.session.execute(stmt)).scalar_one_or_none()
        return int(tenant_user.tenant_id) if tenant_user else None

    async def provision_tenant_for_user(self, email: str, name: str) -> int:
        # PII Removal: Generate a correlation ID instead of logging the raw email
        import uuid

        correlation_id = uuid.uuid4().hex[:8]
        logger.info(f"Initiating JIT provisioning for new user (Correlation: {correlation_id})")

        # Find default shard
        shard_stmt = select(DatabaseShard).where(DatabaseShard.name == "shard_1")
        shard = (await self.session.execute(shard_stmt)).scalar_one_or_none()
        if not shard:
            raise RuntimeError("Default shard not found for provisioning")

        # 1. Create User
        user = User(email=email.lower(), name=name or str(email).split("@")[0])
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError as e:
            # Race condition: User was created by a concurrent request.
            await self.session.rollback()
            logger.info(
                f"Concurrent JIT provisioning detected. Re-fetching (Correlation: {correlation_id})"
            )
            user_id = await self.get_user_id_by_email(email)
            if not user_id:
                raise RuntimeError("Failed to re-fetch user after IntegrityError") from e
            tenant_id = await self.get_tenant_id_for_user(user_id)
            if tenant_id is None:
                # User exists but no tenant mapping yet.
                # In a robust system, we would retry or implement an upsert here.
                # For simplicity, we just fail and let the client retry.
                raise RuntimeError("Concurrent provisioning incomplete. Please retry.") from e
            return tenant_id

        # 2. Create Tenant
        tenant_uuid = uuid.uuid4().hex
        tenant = Tenant(
            name=f"{user.name}'s Organization ({tenant_uuid})",
            shard_id=int(shard.id),
            shard_schema=f"tenant_{tenant_uuid}",
        )
        self.session.add(tenant)
        await self.session.flush()

        # 3. Create TenantUser map
        tenant_user = TenantUser(tenant_id=int(tenant.id), user_id=int(user.id), role="admin")
        self.session.add(tenant_user)

        await self.session.commit()
        logger.info(
            f"JIT Provisioned new tenant ID {tenant.id} for user (Correlation: {correlation_id})"
        )
        return int(tenant.id)
