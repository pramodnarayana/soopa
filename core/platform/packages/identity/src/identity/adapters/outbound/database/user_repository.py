from datetime import UTC, datetime

import structlog
from config_sync.domain.enums import ConfigChangeAction
from database.models.identity import IdentityOutbox, Role, TenantUser, UserRole
from database.models.identity import User as DbUser
from database.outbox_serializer import serialize_domain_event
from seedwork.utils import generate_id
from sqlalchemy import and_, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from identity.adapters.outbound.database._invalidation import record_user_revocation_tombstone
from identity.domain.constants import MembershipScope, MembershipStatus, UserStatus
from identity.domain.identity_context import PLATFORM_TENANT_ID
from identity.domain.user import User
from identity.ports.outbound.user_repository_port import UserRepositoryPort

logger = structlog.get_logger(__name__)


def _safe_user_status(status_str: str) -> UserStatus:
    try:
        return UserStatus(status_str)
    except ValueError:
        logger.error("invalid_user_status_found", status=status_str)
        return UserStatus.INACTIVE


class SqlAlchemyUserRepository(UserRepositoryPort):
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_domain_model(db_user: DbUser, role: str | None = None) -> User:
        user = User(
            id=db_user.id,
            idp_user_id=db_user.idp_user_id,
            email=db_user.email,
            name=db_user.name or "",
            status=_safe_user_status(db_user.status),
            created_at=db_user.created_at.replace(tzinfo=UTC),
            updated_at=db_user.updated_at.replace(tzinfo=UTC),
        )
        if role is not None:
            user.role = role
        return user

    @staticmethod
    def _to_orm_record(user: User) -> DbUser:
        return DbUser(
            id=user.id,
            idp_user_id=user.idp_user_id,
            email=user.email,
            name=user.name,
            status=user.status.value,
            created_at=user.created_at.replace(tzinfo=None),
        )

    @staticmethod
    def _update_record_from_domain(db_user: DbUser, user: User) -> None:
        db_user.email = user.email
        db_user.name = user.name
        db_user.idp_user_id = user.idp_user_id
        db_user.status = user.status.value

    async def has_any_tenant_memberships(self, user_id: str) -> bool:
        stmt = (
            select(TenantUser.tenant_id)
            .where(
                TenantUser.user_id == user_id,
                TenantUser.tenant_id != PLATFORM_TENANT_ID,
                TenantUser.active.is_(True),
                TenantUser.status == MembershipStatus.ACTIVE.value,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def upsert_tenant_membership(
        self,
        *,
        tenant_id: str,
        user_id: str,
        scope: MembershipScope = MembershipScope.DIRECT,
        status: MembershipStatus = MembershipStatus.ACTIVE,
    ) -> None:
        is_active = status == MembershipStatus.ACTIVE
        now = datetime.now(UTC).replace(tzinfo=None)
        stmt = (
            pg_insert(TenantUser)
            .values(
                user_id=user_id,
                tenant_id=tenant_id,
                scope=scope.value,
                status=status.value,
                active=is_active,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[TenantUser.user_id, TenantUser.tenant_id],
                set_={
                    "scope": scope.value,
                    "status": status.value,
                    "active": is_active,
                    "updated_at": now,
                },
            )
        )
        await self.session.execute(stmt)
        await record_user_revocation_tombstone(
            self.session,
            tenant_id=tenant_id,
            user_id=user_id,
            action=ConfigChangeAction.UPSERT,
            reason="tenant_membership_upserted",
        )

    async def remove_tenant_membership(self, *, tenant_id: str, user_id: str) -> None:
        await self.session.execute(
            delete(TenantUser).where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.user_id == user_id,
            )
        )
        await record_user_revocation_tombstone(
            self.session,
            tenant_id=tenant_id,
            user_id=user_id,
            action=ConfigChangeAction.DELETE,
            reason="tenant_membership_removed",
        )

    async def find_users_by_tenant(self, tenant_id: str) -> list[User]:
        stmt = (
            select(DbUser, Role.name)
            .join(
                TenantUser,
                and_(
                    TenantUser.user_id == DbUser.id,
                    TenantUser.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                UserRole,
                and_(
                    UserRole.user_id == DbUser.id,
                    UserRole.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                Role,
                and_(
                    Role.id == UserRole.role_id,
                    Role.deleted_at.is_(None),
                ),
            )
            .where(DbUser.deleted_at.is_(None))
            .order_by(DbUser.id, Role.name)
        )
        result = await self.session.execute(stmt)
        rows = result.all()

        users_by_id: dict[str, User] = {}
        for db_user, role in rows:
            if db_user.id not in users_by_id:
                # Enforce a canonical role (alphabetically first) when multiple exist
                users_by_id[db_user.id] = self._to_domain_model(db_user, role=role)

        return list(users_by_id.values())

    async def find_by_email(self, email: str) -> User | None:
        stmt = select(DbUser).where(and_(DbUser.email == email, DbUser.deleted_at.is_(None)))
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if not db_user:
            return None

        return self._to_domain_model(db_user)

    async def find_by_idp_user_id(self, idp_user_id: str) -> User | None:
        stmt = select(DbUser).where(
            and_(DbUser.idp_user_id == idp_user_id, DbUser.deleted_at.is_(None))
        )
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if not db_user:
            return None

        return self._to_domain_model(db_user)

    async def find_by_id(self, user_id: str) -> User | None:
        stmt = select(DbUser).where(and_(DbUser.id == user_id, DbUser.deleted_at.is_(None)))
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if not db_user:
            return None

        return self._to_domain_model(db_user)

    async def find_by_id_and_tenant(self, user_id: str, tenant_id: str) -> User | None:
        stmt = (
            select(DbUser, Role.name)
            .join(
                TenantUser,
                and_(
                    TenantUser.user_id == DbUser.id,
                    TenantUser.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                UserRole,
                and_(
                    UserRole.user_id == DbUser.id,
                    UserRole.tenant_id == tenant_id,
                ),
            )
            .outerjoin(
                Role,
                and_(
                    Role.id == UserRole.role_id,
                    Role.deleted_at.is_(None),
                ),
            )
            .where(
                and_(
                    DbUser.id == user_id,
                    DbUser.deleted_at.is_(None),
                )
            )
            .order_by(Role.name)
        )
        result = await self.session.execute(stmt)
        # Enforce canonical role deterministically (alphabetically first)
        row = result.first()

        if not row:
            return None

        db_user, role = row
        return self._to_domain_model(db_user, role=role)

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
        await record_user_revocation_tombstone(
            self.session,
            tenant_id=PLATFORM_TENANT_ID,
            user_id=user.id,
            action=ConfigChangeAction.DELETE,
            reason="user_deleted",
        )
        self._flush_events(user)

    async def save(self, user: User) -> None:
        stmt = select(DbUser).where(DbUser.id == user.id)
        result = await self.session.execute(stmt)
        db_user = result.scalar_one_or_none()

        if db_user:
            self._update_record_from_domain(db_user, user)
        else:
            db_user = self._to_orm_record(user)
            self.session.add(db_user)

        self._flush_events(user)

    def _flush_events(self, user: User, idempotency_key: str | None = None) -> None:

        for index, event in enumerate(user.domain_events):
            outbox_id = generate_id(IdentityOutbox.ID_PREFIX)
            event_name = event.event_name

            final_idemp_key = (
                f"{idempotency_key}_{index}" if idempotency_key else event.idempotency_key
            )
            payload_dict = serialize_domain_event(event)

            outbox_event = IdentityOutbox(
                id=outbox_id,
                idempotency_key=final_idemp_key,
                tenant_id=event.get_routing_tenant_id() or PLATFORM_TENANT_ID,
                event_type=event_name,
                payload=payload_dict,
            )
            self.session.add(outbox_event)

        user.clear_domain_events()
