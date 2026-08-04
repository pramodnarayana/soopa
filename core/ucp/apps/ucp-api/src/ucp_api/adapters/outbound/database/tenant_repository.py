import json
import os
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, text
from datetime import datetime, timezone

from ucp_api.ports.outbound.tenant_repository import ITenantRepository
from ucp_api.domain.models.tenant import Tenant
from ucp_models.subscriptions import AppSubscription
from ucp_models.subscriptions import App
from ucp_models.infrastructure import ShardRegistry
from ucp_models.identity import TenantUser
from ucp_models.identity import Tenant as DbTenant
from ucp_models.identity import ApiToken
from ucp_models.events import ControlPlaneOutbox


class TenantRepository(ITenantRepository):
    def __init__(self, session: AsyncSession):
        self.session = session

    def _map_to_domain(self, row: DbTenant, subscriptions: Optional[List[str]] = None) -> Tenant:  # type: ignore
        return Tenant(
            id=row.id,
            name=row.name,
            idp_tenant_id=row.idp_tenant_id,
            status=row.status if hasattr(row, "status") else "active",
            created_at=row.created_at.replace(tzinfo=timezone.utc),
            updated_at=(
                row.updated_at.replace(tzinfo=timezone.utc)
                if hasattr(row, "updated_at") and row.updated_at
                else row.created_at.replace(tzinfo=timezone.utc)
            ),
            subscriptions=subscriptions or [],
        )

    async def find_by_id(self, id: str) -> Optional[Tenant]:
        stmt = select(DbTenant).where(DbTenant.id == id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        subs = await self._load_subscription_slugs(row.id)
        return self._map_to_domain(row, subs)

    async def find_by_idp_tenant_id(self, idp_tenant_id: str) -> Optional[Tenant]:
        stmt = select(DbTenant).where(DbTenant.idp_tenant_id == idp_tenant_id)
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        subs = await self._load_subscription_slugs(row.id)
        return self._map_to_domain(row, subs)

    async def find_all(self) -> List[Tenant]:
        stmt = select(DbTenant)
        result = await self.session.execute(stmt)
        rows = result.scalars().all()

        if not rows:
            return []

        # Bulk-fetch all subscription slugs in one query
        tenant_ids = [row.id for row in rows]
        stmt_subs = (
            select(AppSubscription.tenant_id, App.slug)
            .select_from(AppSubscription)
            .join(App, AppSubscription.app_id == App.id)
            .where(AppSubscription.tenant_id.in_(tenant_ids))
        )
        subs_result = await self.session.execute(stmt_subs)

        # Group slugs by tenant_id
        subs_by_tenant: dict[str, List[str]] = {}
        for tenant_id, slug in subs_result:
            subs_by_tenant.setdefault(tenant_id, []).append(slug)

        tenants = []
        for row in rows:
            subs = subs_by_tenant.get(row.id, [])
            tenants.append(self._map_to_domain(row, subs))
        return tenants

    async def save(self, tenant: Tenant, idempotency_key: Optional[str] = None) -> None:
        # 1. Save Tenant
        stmt = select(DbTenant).where(DbTenant.id == tenant.id)
        result = await self.session.execute(stmt)
        db_tenant = result.scalar_one_or_none()

        if db_tenant:
            db_tenant.name = tenant.name
            db_tenant.idp_tenant_id = tenant.idp_tenant_id
        else:
            db_tenant = DbTenant(
                id=tenant.id,
                name=tenant.name,
                idp_tenant_id=tenant.idp_tenant_id,
                created_at=tenant.created_at.replace(tzinfo=None),
            )
            self.session.add(db_tenant)

        # 2. Save Subscriptions via precise diffing
        # Fetch existing subscriptions
        stmt_subs = select(AppSubscription).where(AppSubscription.tenant_id == tenant.id)
        existing_subs = (await self.session.execute(stmt_subs)).scalars().all()
        existing_app_ids = {sub.app_id for sub in existing_subs}

        target_app_ids = set()
        if tenant.subscriptions:
            stmt_apps = select(App.id).where(App.slug.in_(tenant.subscriptions))
            target_app_ids = set((await self.session.execute(stmt_apps)).scalars().all())

        # Subscriptions to delete
        apps_to_delete = existing_app_ids - target_app_ids
        if apps_to_delete:
            await self.session.execute(
                delete(AppSubscription).where(
                    AppSubscription.tenant_id == tenant.id,
                    AppSubscription.app_id.in_(apps_to_delete),
                )
            )

        # Subscriptions to insert
        apps_to_insert = target_app_ids - existing_app_ids
        for app_id in apps_to_insert:
            sub = AppSubscription(tenant_id=tenant.id, app_id=app_id, tier="standard")
            self.session.add(sub)

        # 3. Process Outbox Events (Domain Events)
        for index, event in enumerate(tenant.domain_events):
            outbox_id = f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}"
            event_name = event.__class__.__name__
            final_idemp_key = (
                f"{idempotency_key}_{index}"
                if idempotency_key
                else f"{event_name}_{tenant.id}_{datetime.now(timezone.utc).timestamp()}"
            )

            outbox_event = ControlPlaneOutbox(
                id=outbox_id,
                idempotency_key=final_idemp_key,
                tenant_id=tenant.id,
                event_type=event_name,
                payload=json.loads(event.model_dump_json()),
            )
            self.session.add(outbox_event)
            # Fire Postgres NOTIFY so the OutboxListener instantly wakes up
            await self.session.execute(
                text("SELECT pg_notify('control_plane_outbox_channel', :outbox_id)"),
                {"outbox_id": outbox_id},
            )

        tenant.clear_domain_events()

    async def delete(self, tenant_id: str, idempotency_key: Optional[str] = None) -> None:
        await self.session.execute(delete(TenantUser).where(TenantUser.tenant_id == tenant_id))
        await self.session.execute(delete(ApiToken).where(ApiToken.tenant_id == tenant_id))
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

    async def _load_subscription_slugs(self, tenant_id: str) -> List[str]:
        stmt = (
            select(App.slug)
            .select_from(AppSubscription)
            .join(App, AppSubscription.app_id == App.id)
            .where(AppSubscription.tenant_id == tenant_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
