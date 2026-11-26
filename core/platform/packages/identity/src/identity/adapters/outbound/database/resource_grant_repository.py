"""SQLAlchemy adapter for indexed ReBAC resource grants (`identity.resource_grants`)."""

from __future__ import annotations

from collections.abc import Sequence

from database.models.identity import ResourceGrant as OrmResourceGrant
from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from identity.domain.constants import AuthzEffect, ResourceSubjectType
from identity.domain.dtos import ResourceGrantDTO
from identity.ports.outbound.resource_grant_repository_port import ResourceGrantRepositoryPort


class SqlAlchemyResourceGrantRepository(ResourceGrantRepositoryPort):
    """PostgreSQL covering-index ReBAC resource grant repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _to_dto(row: OrmResourceGrant) -> ResourceGrantDTO:
        return ResourceGrantDTO(
            id=row.id,
            tenant_id=row.tenant_id,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            relation=row.relation,
            subject_type=ResourceSubjectType(row.subject_type),
            subject_id=row.subject_id,
            effect=AuthzEffect(row.effect),
            expires_at=row.expires_at,
        )

    async def find_matching_grants(
        self,
        *,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        user_id: str,
        role_ids: Sequence[str],
    ) -> tuple[ResourceGrantDTO, ...]:
        subject_clauses = [
            and_(
                OrmResourceGrant.subject_type == ResourceSubjectType.USER.value,
                OrmResourceGrant.subject_id == user_id,
            ),
            and_(
                OrmResourceGrant.subject_type == ResourceSubjectType.TENANT.value,
                OrmResourceGrant.subject_id == tenant_id,
            ),
        ]
        if role_ids:
            subject_clauses.append(
                and_(
                    OrmResourceGrant.subject_type == ResourceSubjectType.ROLE.value,
                    OrmResourceGrant.subject_id.in_(tuple(role_ids)),
                )
            )

        stmt = select(OrmResourceGrant).where(
            OrmResourceGrant.tenant_id == tenant_id,
            OrmResourceGrant.resource_type == resource_type,
            OrmResourceGrant.resource_id == resource_id,
            or_(*subject_clauses),
        )
        res = await self._session.execute(stmt)
        return tuple(self._to_dto(row) for row in res.scalars().all())

    async def save_grant(self, grant: ResourceGrantDTO) -> ResourceGrantDTO:
        existing = await self._session.get(OrmResourceGrant, grant.id)
        if existing is None:
            row = OrmResourceGrant(
                id=grant.id,
                tenant_id=grant.tenant_id,
                resource_type=grant.resource_type,
                resource_id=grant.resource_id,
                relation=grant.relation,
                subject_type=grant.subject_type.value,
                subject_id=grant.subject_id,
                effect=grant.effect.value,
                expires_at=grant.expires_at,
            )
            self._session.add(row)
        else:
            existing.relation = grant.relation
            existing.effect = grant.effect.value
            existing.expires_at = grant.expires_at
        await self._session.flush()
        return grant

    async def revoke_grant(self, *, tenant_id: str, grant_id: str) -> bool:
        stmt = (
            delete(OrmResourceGrant)
            .where(
                OrmResourceGrant.tenant_id == tenant_id,
                OrmResourceGrant.id == grant_id,
            )
            .returning(OrmResourceGrant.id)
        )
        res = await self._session.execute(stmt)
        return res.scalar_one_or_none() is not None

    async def list_grants_for_resource(
        self,
        *,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
    ) -> tuple[ResourceGrantDTO, ...]:
        stmt = (
            select(OrmResourceGrant)
            .where(
                OrmResourceGrant.tenant_id == tenant_id,
                OrmResourceGrant.resource_type == resource_type,
                OrmResourceGrant.resource_id == resource_id,
            )
            .order_by(OrmResourceGrant.created_at.asc())
        )
        res = await self._session.execute(stmt)
        return tuple(self._to_dto(row) for row in res.scalars().all())


__all__ = ["SqlAlchemyResourceGrantRepository"]
