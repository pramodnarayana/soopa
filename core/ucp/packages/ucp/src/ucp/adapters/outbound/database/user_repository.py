from datetime import UTC, datetime
from typing import Literal, cast

import structlog

logger = structlog.get_logger(__name__)

from platform_orm.models.identity import Role, UserRole
from platform_orm.models.identity import User as DbUser
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import ControlPlaneOutbox

from ucp.domain.models.user import User
from ucp.ports.outbound.user_repository import IUserRepository


class UserRepository(IUserRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        stmt = select(UserRole).where(UserRole.user_id == user_id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def find_users_by_tenant(self, tenant_id: str) -> list[User]:
        stmt = (
            select(DbUser, Role.name)
            .join(UserRole, UserRole.user_id == DbUser.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(and_(UserRole.tenant_id == tenant_id, DbUser.deleted_at.is_(None)))
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

    async def find_by_idp_user_id(self, idp_user_id: str) -> User | None:
        stmt = select(DbUser).where(
            and_(DbUser.idp_user_id == idp_user_id, DbUser.deleted_at.is_(None))
        )
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

    async def find_by_id(self, user_id: str) -> User | None:
        stmt = select(DbUser).where(and_(DbUser.id == user_id, DbUser.deleted_at.is_(None)))
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
            select(DbUser, Role.name)
            .join(UserRole, UserRole.user_id == DbUser.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(
                and_(
                    UserRole.tenant_id == tenant_id,
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

    def _flush_events(self, user: User, idempotency_key: str | None = None) -> None:
        import json
        import os

        for index, event in enumerate(user.domain_events):
            outbox_id = f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}"
            event_name = event.event_name

            payload_dict = json.loads(event.model_dump_json())
            tenant_id = event.get_routing_tenant_id()
            if tenant_id is None and event_name != "UserDeleted":
                # Only global events are allowed to have a null tenant ID. In practice, the Outbox table
                # might enforce NOT NULL. If it does, we need a fallback or fail fast.
                logger.error(
                    "outbox_event_missing_tenant_id",
                    event_name=event_name,
                    event_payload=payload_dict,
                )
                # If outbox requires it, we raise here to fail fast instead of hitting DB constraint
                # raise ValueError(f"Event {event_name} missing required routing tenant_id")
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
