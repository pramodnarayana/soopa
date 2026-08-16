from datetime import UTC, datetime
from typing import Literal, cast

from platform_orm.models.identity import TenantUser
from platform_orm.models.identity import User as DbUser
from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import ControlPlaneOutbox

from ucp.domain.models.user import User
from ucp.ports.outbound.user_repository import IUserRepository


class UserRepository(IUserRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_users_by_tenant(self, tenant_id: str) -> list[User]:
        stmt = (
            select(DbUser, TenantUser.role)
            .join(TenantUser, TenantUser.user_id == DbUser.id)
            .where(and_(TenantUser.tenant_id == tenant_id, DbUser.deleted_at.is_(None)))
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

    async def find_by_email(self, email: str) -> User | None:
        stmt = select(DbUser).where(and_(DbUser.email == email, DbUser.deleted_at.is_(None)))
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if not db_user:
            return None

        return User(
            id=db_user.id,
            idp_user_id=db_user.idp_user_id,
            email=db_user.email,
            name=db_user.name or "",
            status=cast(Literal["active", "inactive"], db_user.status),
            created_at=db_user.created_at.replace(tzinfo=UTC),
            updated_at=db_user.updated_at.replace(tzinfo=UTC),
        )

    async def find_by_id_and_tenant(self, user_id: str, tenant_id: str) -> User | None:
        stmt = (
            select(DbUser, TenantUser.role)
            .join(TenantUser, TenantUser.user_id == DbUser.id)
            .where(
                and_(
                    TenantUser.tenant_id == tenant_id,
                    DbUser.id == user_id,
                    DbUser.deleted_at.is_(None),
                )
            )
        )
        result = await self.session.execute(stmt)
        row = result.first()

        if not row:
            return None

        db_user, role = row
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
        return u

    async def delete(self, user: User) -> None:
        stmt = select(DbUser).where(DbUser.id == user.id)
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()
        if db_user:
            db_user.deleted_at = (
                user.deleted_at.replace(tzinfo=None)
                if user.deleted_at
                else datetime.now(UTC).replace(tzinfo=None)
            )
        self._flush_events(user)

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

        self._flush_events(user)

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

    async def remove_tenant_membership(self, tenant_id: str, user: User) -> None:
        stmt = delete(TenantUser).where(
            and_(TenantUser.tenant_id == tenant_id, TenantUser.user_id == user.id)
        )
        await self.session.execute(stmt)
        self._flush_events(user)

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        """Check if a user has any remaining tenant memberships."""
        stmt = select(TenantUser).where(TenantUser.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.first() is not None

    def _flush_events(self, user: User, idempotency_key: str | None = None) -> None:
        import json
        import os

        for index, event in enumerate(user.domain_events):
            outbox_id = f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}"
            event_name = event.event_name

            # In UCP outbox, tenant_id is traditionally used to shard events or partition them.
            # If an event has an org_id (like UserUpdatedEvent), we can infer it.
            # Alternatively, we can leave it null if it's a global user event, but the DB schema might require it.
            # Wait, the DB schema has tenant_id nullable=True!
            # Let's extract org_id if it exists.
            payload_dict = json.loads(event.model_dump_json())
            tenant_id = getattr(event, "org_id", None) or payload_dict.get("org_id", None)

            final_idemp_key = (
                f"{idempotency_key}_{index}"
                if idempotency_key
                else getattr(event, "id", f"{event_name}_{user.id}_{index}")
            )

            outbox_event = ControlPlaneOutbox(
                id=outbox_id,
                idempotency_key=final_idemp_key,
                tenant_id=tenant_id,
                event_type=event_name,
                payload=payload_dict,
            )
            self.session.add(outbox_event)

        user.clear_domain_events()
