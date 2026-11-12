"""SQLAlchemy Control Plane adapter implementing TenantRepositoryPort."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.domain.authorization import TenantSummary
from ip.engine.ports.outbound.tenant_repository_port import TenantRepositoryPort
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.identity import Tenant


class SqlAlchemyTenantRepository(GlobalSqlAlchemyRepository, TenantRepositoryPort):
    """Read-only SQLAlchemy repository resolving canonical UCP tenants from `identity.tenants`."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _to_domain_model(record: Tenant) -> TenantSummary:
        """Strict explicit data mapper from `identity.tenants` ORM record to `TenantSummary`."""
        return TenantSummary(
            id=record.id,
            slug=record.slug,
            idp_tenant_id=record.idp_tenant_id,
            name=record.name,
        )

    async def get_by_idp_tenant_id(self, idp_tenant_id: str) -> TenantSummary | None:
        normalized = idp_tenant_id.strip()
        if not normalized:
            return None
        stmt = (
            select(Tenant)
            .where(
                Tenant.idp_tenant_id == normalized,
                Tenant.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain_model(record)

    async def get_by_slug(self, tenant_slug: str) -> TenantSummary | None:
        normalized = tenant_slug.strip().lower()
        if not normalized:
            return None
        stmt = (
            select(Tenant)
            .where(
                Tenant.slug == normalized,
                Tenant.deleted_at.is_(None),
            )
            .limit(1)
        )
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return self._to_domain_model(record)


class SessionScopedTenantRepository(TenantRepositoryPort):
    """Short-lived session-opening `TenantRepositoryPort` delegating to an injected `repository_factory`."""

    def __init__(
        self,
        *,
        session_scope: Callable[[], AbstractAsyncContextManager[AsyncSession]],
        repository_factory: Callable[[AsyncSession], TenantRepositoryPort],
    ) -> None:
        self._session_scope = session_scope
        self._repository_factory = repository_factory

    async def get_by_idp_tenant_id(self, idp_tenant_id: str) -> TenantSummary | None:
        async with self._session_scope() as session:
            return await self._repository_factory(session).get_by_idp_tenant_id(idp_tenant_id)

    async def get_by_slug(self, tenant_slug: str) -> TenantSummary | None:
        async with self._session_scope() as session:
            return await self._repository_factory(session).get_by_slug(tenant_slug)


__all__ = ["SessionScopedTenantRepository", "SqlAlchemyTenantRepository"]
