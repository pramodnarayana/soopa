import typing
from datetime import UTC

import structlog
from database.models.identity import Tenant as DbTenant
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.subscriptions import App, AppSubscription

from ucp.domain.constants import LifecycleStatus
from ucp.ports.outbound.tenant_query_service_port import (
    PaginatedTenants,
    TenantQueryServicePort,
    TenantReadModel,
)

logger = structlog.get_logger(__name__)


class DatabaseTenantQueryService(TenantQueryServicePort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Private mapper — single source of truth for DbTenant → TenantReadModel.
    # Fixes C2 (DRY violation: 3 identical construction blocks collapsed to 1).
    # ------------------------------------------------------------------

    def _map_row(self, row: DbTenant, app_slugs: list[str]) -> TenantReadModel:
        return TenantReadModel(
            id=row.id,
            name=row.name,
            slug=row.slug,
            idp_tenant_id=row.idp_tenant_id,
            status=typing.cast(
                typing.Literal["active", "inactive"],
                row.status,
            ),
            subscriptions=app_slugs,
            created_at=row.created_at.replace(tzinfo=UTC),
            updated_at=row.updated_at.replace(tzinfo=UTC),
        )

    async def _load_app_slugs(self, tenant_id: str) -> list[str]:
        """Loads active application slugs for a single tenant."""
        stmt = (
            select(App.slug)
            .join(AppSubscription, App.id == AppSubscription.app_id)
            .where(
                AppSubscription.tenant_id == tenant_id,
                AppSubscription.status == LifecycleStatus.ACTIVE,
            )
        )
        result = await self.session.execute(stmt)
        # 'ucp_app_slug' avoids shadowing any outer variable named 'slug' — fixes B2.
        return [app_slug for (app_slug,) in result]

    # ------------------------------------------------------------------
    # Public query methods
    # ------------------------------------------------------------------

    async def get_all_tenants(self, page: int = 1, limit: int = 50) -> PaginatedTenants:
        offset = (page - 1) * limit

        # Get total count
        count_stmt = select(func.count(DbTenant.id)).where(DbTenant.deleted_at.is_(None))
        total = await self.session.scalar(count_stmt) or 0

        if total == 0:
            return PaginatedTenants(items=[], total=0, page=page, limit=limit)

        stmt = (
            select(DbTenant)
            .where(DbTenant.deleted_at.is_(None))
            .order_by(DbTenant.id)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            return PaginatedTenants(items=[], total=total, page=page, limit=limit)

        tenant_ids = [row.id for row in rows]
        stmt_subs = (
            select(AppSubscription.tenant_id, App.slug)
            .join(App, App.id == AppSubscription.app_id)
            .where(
                AppSubscription.tenant_id.in_(tenant_ids),
                AppSubscription.status == LifecycleStatus.ACTIVE,
            )
        )
        subs_result = await self.session.execute(stmt_subs)

        subs_by_tenant: dict[str, list[str]] = {}
        for tenant_id, app_slug in subs_result:
            subs_by_tenant.setdefault(tenant_id, []).append(app_slug)

        items = [self._map_row(row, subs_by_tenant.get(row.id, [])) for row in rows]
        return PaginatedTenants(items=items, total=total, page=page, limit=limit)

    async def get_tenant_by_id(self, tenant_id: str) -> TenantReadModel | None:
        stmt = select(DbTenant).where(
            ((DbTenant.id == tenant_id) | (DbTenant.idp_tenant_id == tenant_id))
            & DbTenant.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            logger.info("tenant_query.not_found_by_id", tenant_id=tenant_id)
            return None

        app_slugs = await self._load_app_slugs(row.id)
        return self._map_row(row, app_slugs)

    async def get_tenant_by_slug(self, slug: str) -> TenantReadModel | None:
        stmt = select(DbTenant).where(DbTenant.slug == slug, DbTenant.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            logger.info("tenant_query.not_found_by_slug", slug=slug)
            return None

        app_slugs = await self._load_app_slugs(row.id)
        return self._map_row(row, app_slugs)
