"""UCP outbound adapter implementing identity's TenantEntitlementPort (zero identity -> ucp coupling)."""

from __future__ import annotations

from database.models.subscriptions import App as OrmApp
from database.models.subscriptions import AppSubscription as OrmAppSubscription
from identity.ports.outbound.tenant_entitlement_port import TenantEntitlementPort
from seedwork.constants import LifecycleStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyTenantEntitlementRepository(TenantEntitlementPort):
    """Queries `ucp.app_subscriptions` joined with `ucp.apps` to resolve active app slugs."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_enabled_app_slugs(self, *, tenant_id: str) -> frozenset[str]:
        stmt = (
            select(OrmApp.slug)
            .join(OrmAppSubscription, OrmAppSubscription.app_id == OrmApp.id)
            .where(
                OrmAppSubscription.tenant_id == tenant_id,
                OrmAppSubscription.status == LifecycleStatus.ACTIVE.value,
            )
        )
        res = await self._session.execute(stmt)
        return frozenset(slug.strip().lower() for slug in res.scalars().all() if slug)

    async def is_app_enabled(self, *, tenant_id: str, app_slug: str) -> bool:
        normalized = app_slug.strip().lower()
        enabled = await self.get_enabled_app_slugs(tenant_id=tenant_id)
        return normalized in enabled


__all__ = ["SqlAlchemyTenantEntitlementRepository"]
