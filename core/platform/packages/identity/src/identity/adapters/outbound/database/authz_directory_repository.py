"""SQLAlchemy AuthzDirectoryPort adapter using covering indexes and PostgreSQL ltree."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from database.models.identity import Role as OrmRole
from database.models.identity import Tenant as OrmTenant
from database.models.identity import TenantUser as OrmTenantUser
from database.models.identity import User as OrmUser
from database.models.identity import UserRole as OrmUserRole
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from identity.domain.constants import (
    MembershipScope,
    MembershipStatus,
    TenantIsolationMode,
    TenantTierType,
    UserStatus,
)
from identity.domain.dtos import (
    MembershipDTO,
    PrincipalSnapshotDTO,
    RoleDefinitionDTO,
    TenantNodeDTO,
    UserRoleAssignmentDTO,
)
from identity.domain.hierarchy import parse_ancestor_ids
from identity.ports.outbound.tenant_hierarchy_port import AuthzDirectoryPort

_EPOCH_ZERO = datetime(1970, 1, 1, tzinfo=UTC)


def _ensure_utc(dt: datetime | None) -> datetime:
    if dt is None:
        return _EPOCH_ZERO
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)


class SqlAlchemyAuthzDirectoryRepository(AuthzDirectoryPort):
    """High-cardinality directory lookups backed by PostgreSQL covering indexes & ltree."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_tenant_node(row: OrmTenant) -> TenantNodeDTO:
        return TenantNodeDTO(
            id=row.id,
            parent_tenant_id=row.parent_tenant_id,
            hierarchy_path=str(row.hierarchy_path or row.id),
            tier_type=TenantTierType(row.tier_type),
            isolation_mode=TenantIsolationMode(row.isolation_mode),
            status=row.status,
            block_parent_inheritance=row.block_parent_inheritance,
            tokens_valid_after=_ensure_utc(row.tokens_valid_after),
            idp_realm_name=row.idp_realm_name,
        )

    @staticmethod
    def _to_role_definition(row: OrmRole) -> RoleDefinitionDTO:
        return RoleDefinitionDTO(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            capabilities=frozenset(row.capabilities),
            deny_capabilities=frozenset(row.deny_capabilities),
            is_system=row.is_system,
        )

    async def get_principal_snapshot(self, *, user_id: str) -> PrincipalSnapshotDTO | None:
        user_res = await self._session.execute(
            select(OrmUser).where(OrmUser.id == user_id, OrmUser.deleted_at.is_(None))
        )
        user_row = user_res.scalars().first()
        if user_row is None:
            return None

        mem_res = await self._session.execute(
            select(OrmTenantUser).where(OrmTenantUser.user_id == user_id)
        )
        memberships = tuple(
            MembershipDTO(
                user_id=m.user_id,
                tenant_id=m.tenant_id,
                scope=MembershipScope(m.scope),
                status=(MembershipStatus(m.status) if m.active else MembershipStatus.SUSPENDED),
                expires_at=m.expires_at,
            )
            for m in mem_res.scalars().all()
        )

        role_res = await self._session.execute(
            select(OrmUserRole).where(OrmUserRole.user_id == user_id)
        )
        role_assignments = tuple(
            UserRoleAssignmentDTO(
                tenant_id=r.tenant_id,
                user_id=r.user_id,
                role_id=r.role_id,
                expires_at=r.expires_at,
            )
            for r in role_res.scalars().all()
        )

        return PrincipalSnapshotDTO(
            user_id=user_row.id,
            status=UserStatus(user_row.status),
            tokens_valid_after=_ensure_utc(user_row.tokens_valid_after),
            memberships=memberships,
            role_assignments=role_assignments,
        )

    async def get_tenant_ancestor_chain(self, *, tenant_id: str) -> tuple[TenantNodeDTO, ...]:
        leaf_res = await self._session.execute(
            select(OrmTenant).where(OrmTenant.id == tenant_id, OrmTenant.deleted_at.is_(None))
        )
        leaf = leaf_res.scalars().first()
        if leaf is None:
            return ()

        leaf_node = self._to_tenant_node(leaf)
        ancestor_ids = parse_ancestor_ids(leaf_node.hierarchy_path)
        missing_ids = [aid for aid in ancestor_ids if aid != tenant_id]
        if not missing_ids:
            return (leaf_node,)

        anc_res = await self._session.execute(
            select(OrmTenant).where(
                OrmTenant.id.in_(missing_ids),
                OrmTenant.deleted_at.is_(None),
            )
        )
        by_id: dict[str, TenantNodeDTO] = {tenant_id: leaf_node}
        for row in anc_res.scalars().all():
            by_id[row.id] = self._to_tenant_node(row)

        ordered = [by_id[aid] for aid in ancestor_ids if aid in by_id]
        if tenant_id not in ancestor_ids:
            ordered.append(leaf_node)
        return tuple(ordered)

    async def get_roles_by_ids(self, *, role_ids: Sequence[str]) -> dict[str, RoleDefinitionDTO]:
        unique_ids = tuple(dict.fromkeys(role_ids))
        if not unique_ids:
            return {}
        res = await self._session.execute(
            select(OrmRole).where(
                OrmRole.id.in_(unique_ids),
                OrmRole.deleted_at.is_(None),
            )
        )
        return {row.id: self._to_role_definition(row) for row in res.scalars().all()}


__all__ = ["SqlAlchemyAuthzDirectoryRepository"]
