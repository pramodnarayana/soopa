import os

import structlog
from database.outbox_serializer import serialize_domain_event

logger = structlog.get_logger(__name__)
import typing
from datetime import UTC, datetime

from database.models.identity import ApiKey, ApiToken, Role, UserRole
from database.models.identity import Tenant as DbTenant
from database.models.webhooks import Webhook
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import ControlPlaneOutbox
from ucp_models.infrastructure import ShardRegistry
from ucp_models.subscriptions import AppSubscription

from ucp.domain.models.tenant import Tenant, TenantSubscription
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort


class TenantRepository(TenantRepositoryPort):
    def __init__(self, session: AsyncSession):
        self.session = session

    def _map_to_domain(
        self, row: DbTenant, subscriptions: list[TenantSubscription] | None = None
    ) -> Tenant:
        return Tenant(
            id=row.id,
            name=row.name,
            slug=row.slug,
            idp_tenant_id=row.idp_tenant_id,
            status=typing.cast(
                typing.Literal["active", "inactive"],
                row.status,
            ),
            created_at=row.created_at.replace(tzinfo=UTC),
            updated_at=row.updated_at.replace(tzinfo=UTC),
            subscriptions=subscriptions or [],
        )

    async def find_by_id(self, id: str) -> Tenant | None:
        stmt = select(DbTenant).where(DbTenant.id == id, DbTenant.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        subs = await self._load_subscription_ids(row.id)
        return self._map_to_domain(row, subs)

    async def find_by_idp_tenant_id(self, idp_tenant_id: str) -> Tenant | None:
        stmt = select(DbTenant).where(
            DbTenant.idp_tenant_id == idp_tenant_id, DbTenant.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        subs = await self._load_subscription_ids(row.id)
        return self._map_to_domain(row, subs)

    async def find_all(self) -> list[Tenant]:
        stmt = select(DbTenant).where(DbTenant.deleted_at.is_(None))
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
            # Slug is intentionally immutable — not updated on rename.
            # See TECHNICAL_DEBT.md: "Slug Redirect Trail for Self-Service Tenant Portals".
        else:
            db_tenant = DbTenant(
                id=tenant.id,
                name=tenant.name,
                slug=tenant.slug,
                idp_tenant_id=tenant.idp_tenant_id,
                status=tenant.status,
                created_at=tenant.created_at.replace(tzinfo=None),
                updated_at=tenant.updated_at.replace(tzinfo=None),
            )
            self.session.add(db_tenant)

        # 2. Save Subscriptions (Child Entities)
        for sub in tenant.subscriptions:
            await self.upsert_app_subscription(tenant.id, sub.app_id, sub.status)

        # 3. Process Outbox Events (Domain Events)
        self._flush_events(tenant, idempotency_key)

    def _flush_events(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        for index, event in enumerate(tenant.domain_events):
            outbox_id = f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}"
            event_name = event.event_name

            final_idemp_key = (
                f"{idempotency_key}_{index}"
                if idempotency_key
                else getattr(event, "id", f"{event_name}_{tenant.id}_{index}")
            )

            payload_dict = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id()
            if tenant_id is None:
                logger.error(
                    "outbox_event_missing_tenant_id",
                    event_name=event_name,
                    event_payload=payload_dict,
                )

            outbox_event = ControlPlaneOutbox(
                id=outbox_id,
                idempotency_key=final_idemp_key,
                tenant_id=tenant_id,
                event_type=event_name,
                payload=payload_dict,
            )
            self.session.add(outbox_event)

        tenant.clear_domain_events()

    async def delete(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        tenant_id = tenant.id
        self._flush_events(tenant, idempotency_key)

        # Soft delete the DbTenant record
        stmt = select(DbTenant).where(DbTenant.id == tenant_id)
        result = await self.session.execute(stmt)
        db_tenant = result.scalar_one_or_none()
        if db_tenant:
            db_tenant.deleted_at = (
                tenant.deleted_at.replace(tzinfo=None)
                if tenant.deleted_at
                else datetime.now(UTC).replace(tzinfo=None)
            )

        # Hard delete junction/metadata tables
        await self.session.execute(delete(UserRole).where(UserRole.tenant_id == tenant_id))
        await self.session.execute(
            delete(ShardRegistry).where(ShardRegistry.tenant_id == tenant_id)
        )
        await self.session.execute(
            delete(AppSubscription).where(AppSubscription.tenant_id == tenant_id)
        )

        # Note: ApiToken, ApiKey, Webhook, and Role cascades are handled asynchronously via TenantDeletedEventHandler
        # They will call soft_delete_tenant_infrastructure in a separate transaction

    async def soft_delete_tenant_infrastructure(self, tenant_id: str) -> None:
        now = datetime.now(UTC).replace(tzinfo=None)

        # Soft delete Webhooks
        await self.session.execute(
            update(Webhook)
            .where(Webhook.tenant_id == tenant_id, Webhook.deleted_at.is_(None))
            .values(deleted_at=now)
        )

        # Soft delete Roles
        await self.session.execute(
            update(Role)
            .where(Role.tenant_id == tenant_id, Role.deleted_at.is_(None))
            .values(deleted_at=now)
        )

        # Soft delete ApiTokens
        await self.session.execute(
            update(ApiToken)
            .where(ApiToken.tenant_id == tenant_id, ApiToken.deleted_at.is_(None))
            .values(deleted_at=now)
        )

        # Soft delete ApiKeys
        await self.session.execute(
            update(ApiKey)
            .where(ApiKey.tenant_id == tenant_id, ApiKey.deleted_at.is_(None))
            .values(deleted_at=now)
        )

    async def allocate_shard(self, tenant_id: str, app_id: str, shard_id: str) -> None:
        from sqlalchemy.dialects.postgresql import insert

        stmt = insert(ShardRegistry).values(tenant_id=tenant_id, app_id=app_id, shard_id=shard_id)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "app_id"], set_={"shard_id": shard_id}
        )
        await self.session.execute(stmt)

    async def upsert_app_subscription(self, tenant_id: str, app_id: str, status: str) -> None:
        from sqlalchemy.dialects.postgresql import insert

        stmt = insert(AppSubscription).values(
            tenant_id=tenant_id, app_id=app_id, tier="standard", status=status
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["tenant_id", "app_id"], set_={"status": status}
        )
        await self.session.execute(stmt)

    async def _load_subscription_ids(self, tenant_id: str) -> list[TenantSubscription]:
        stmt = select(AppSubscription.app_id, AppSubscription.status).where(
            AppSubscription.tenant_id == tenant_id
        )
        result = await self.session.execute(stmt)
        return [TenantSubscription(app_id=app_id, status=status) for app_id, status in result.all()]


logger = structlog.get_logger(__name__)
