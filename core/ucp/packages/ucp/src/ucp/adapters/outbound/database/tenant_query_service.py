import typing
from datetime import UTC

from platform_orm.models.identity import Tenant as DbTenant
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.subscriptions import App, AppSubscription

from ucp.ports.outbound.tenant_query_service import ITenantQueryService, TenantReadModel


class DatabaseTenantQueryService(ITenantQueryService):
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_all_tenants(self) -> list[TenantReadModel]:
        stmt = select(DbTenant)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            return []

        tenant_ids = [row.id for row in rows]
        stmt_subs = (
            select(AppSubscription.tenant_id, App.slug)
            .join(App, App.id == AppSubscription.app_id)
            .where(AppSubscription.tenant_id.in_(tenant_ids), AppSubscription.status == "active")
        )
        subs_result = await self.session.execute(stmt_subs)

        subs_by_tenant: dict[str, list[str]] = {}
        for tenant_id, app_slug in subs_result:
            subs_by_tenant.setdefault(tenant_id, []).append(app_slug)

        tenants = []
        for row in rows:
            slugs = subs_by_tenant.get(row.id, [])
            tenants.append(
                TenantReadModel(
                    id=row.id,
                    name=row.name,
                    idp_tenant_id=row.idp_tenant_id,
                    status=typing.cast(
                        typing.Literal["active", "inactive"],
                        row.status if hasattr(row, "status") else "active",
                    ),
                    subscriptions=slugs,
                    created_at=row.created_at.replace(tzinfo=UTC),
                    updated_at=(
                        row.updated_at.replace(tzinfo=UTC)
                        if hasattr(row, "updated_at") and row.updated_at
                        else row.created_at.replace(tzinfo=UTC)
                    ),
                )
            )
        return tenants

    async def get_tenant_by_id(self, tenant_id: str) -> TenantReadModel | None:
        stmt = select(DbTenant).where(
            (DbTenant.id == tenant_id) | (DbTenant.idp_tenant_id == tenant_id)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        stmt_subs = (
            select(App.slug)
            .join(AppSubscription, App.id == AppSubscription.app_id)
            .where(AppSubscription.tenant_id == row.id, AppSubscription.status == "active")
        )
        subs_result = await self.session.execute(stmt_subs)
        slugs = [slug for (slug,) in subs_result]

        return TenantReadModel(
            id=row.id,
            name=row.name,
            idp_tenant_id=row.idp_tenant_id,
            status=typing.cast(
                typing.Literal["active", "inactive"],
                row.status if hasattr(row, "status") else "active",
            ),
            subscriptions=slugs,
            created_at=row.created_at.replace(tzinfo=UTC),
            updated_at=(
                row.updated_at.replace(tzinfo=UTC)
                if hasattr(row, "updated_at") and row.updated_at
                else row.created_at.replace(tzinfo=UTC)
            ),
        )
