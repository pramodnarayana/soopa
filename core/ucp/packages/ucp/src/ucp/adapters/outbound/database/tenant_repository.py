import json
import os
import typing
from datetime import UTC

from platform_orm.models.identity import ApiKey, ApiToken, TenantUser
from platform_orm.models.identity import Tenant as DbTenant
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import ControlPlaneOutbox
from ucp_models.infrastructure import ShardRegistry
from ucp_models.subscriptions import AppSubscription

from ucp.domain.models.tenant import Tenant, TenantSubscription
from ucp.ports.outbound.tenant_repository import ITenantRepository


class TenantRepository(ITenantRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    def _map_to_domain(
        self, row: DbTenant, subscriptions: list[TenantSubscription] | None = None
    ) -> Tenant:
        return Tenant(
            id=row.id,
            name=row.name,
            idp_tenant_id=row.idp_tenant_id,
            status=typing.cast(
                typing.Literal["active", "inactive"],
                row.status if hasattr(row, "status") else "active",
            ),
            created_at=row.created_at.replace(tzinfo=UTC),
            updated_at=(
                row.updated_at.replace(tzinfo=UTC)
                if hasattr(row, "updated_at") and row.updated_at
                else row.created_at.replace(tzinfo=UTC)
            ),
            subscriptions=subscriptions or [],
        )

    async def find_by_id(self, id: str) -> Tenant | None:
        stmt = select(DbTenant).where(DbTenant.id == id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        subs = await self._load_subscription_ids(row.id)
        return self._map_to_domain(row, subs)

    async def find_by_idp_tenant_id(self, idp_tenant_id: str) -> Tenant | None:
        stmt = select(DbTenant).where(DbTenant.idp_tenant_id == idp_tenant_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        subs = await self._load_subscription_ids(row.id)
        return self._map_to_domain(row, subs)

    async def find_all(self) -> list[Tenant]:
        stmt = select(DbTenant)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            return []

        # Bulk-fetch all subscription slugs in one query
        tenant_ids = [row.id for row in rows]
        stmt_subs = select(
            AppSubscription.tenant_id, AppSubscription.app_id, AppSubscription.status
        ).where(AppSubscription.tenant_id.in_(tenant_ids))
        subs_result = await self.session.execute(stmt_subs)

        # Group subscriptions by tenant_id
        subs_by_tenant: dict[str, list[TenantSubscription]] = {}
        for tenant_id, app_id, status in subs_result:
            subs_by_tenant.setdefault(tenant_id, []).append(
                TenantSubscription(app_id=app_id, status=status)
            )

        tenants = []
        for row in rows:
            subs = subs_by_tenant.get(row.id, [])
            tenants.append(self._map_to_domain(row, subs))
        return tenants

    async def save(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        # 1. Save Tenant
        stmt = select(DbTenant).where(DbTenant.id == tenant.id)
        result = await self.session.execute(stmt)
        db_tenant = result.scalar_one_or_none()

        if db_tenant:
            db_tenant.name = tenant.name
            db_tenant.idp_tenant_id = tenant.idp_tenant_id
            db_tenant.status = tenant.status
        else:
            db_tenant = DbTenant(
                id=tenant.id,
                name=tenant.name,
                idp_tenant_id=tenant.idp_tenant_id,
                status=tenant.status,
                created_at=tenant.created_at.replace(tzinfo=None),
                updated_at=tenant.updated_at.replace(tzinfo=None),
            )
            self.session.add(db_tenant)

        # 3. Process Outbox Events (Domain Events)
        for index, event in enumerate(tenant.domain_events):
            outbox_id = f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}"
            event_name = event.event_name

            final_idemp_key = (
                f"{idempotency_key}_{index}"
                if idempotency_key
                else getattr(event, "id", f"{event_name}_{tenant.id}_{index}")
            )

            outbox_event = ControlPlaneOutbox(
                id=outbox_id,
                idempotency_key=final_idemp_key,
                tenant_id=tenant.id,
                event_type=event_name,
                payload=json.loads(event.model_dump_json()),
            )
            self.session.add(outbox_event)

    async def delete(self, tenant_id: str, idempotency_key: str | None = None) -> None:
        await self.session.execute(delete(TenantUser).where(TenantUser.tenant_id == tenant_id))
        await self.session.execute(delete(ApiToken).where(ApiToken.tenant_id == tenant_id))
        await self.session.execute(delete(ApiKey).where(ApiKey.tenant_id == tenant_id))
        await self.session.execute(
            delete(ShardRegistry).where(ShardRegistry.tenant_id == tenant_id)
        )
        await self.session.execute(
            delete(AppSubscription).where(AppSubscription.tenant_id == tenant_id)
        )
        await self.session.execute(
            delete(ControlPlaneOutbox).where(ControlPlaneOutbox.tenant_id == tenant_id)
        )
        await self.session.execute(delete(DbTenant).where(DbTenant.id == tenant_id))

    async def _load_subscription_ids(self, tenant_id: str) -> list[TenantSubscription]:
        stmt = select(AppSubscription.app_id, AppSubscription.status).where(
            AppSubscription.tenant_id == tenant_id
        )
        result = await self.session.execute(stmt)
        return [TenantSubscription(app_id=app_id, status=status) for app_id, status in result.all()]
