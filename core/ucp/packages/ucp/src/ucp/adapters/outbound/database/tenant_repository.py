from datetime import UTC, datetime

import structlog
from database.interceptors import intercept_db_errors
from database.models.identity import ApiKey, ApiToken, Role, UserRole
from database.models.identity import Tenant as DbTenant
from database.models.webhooks import Webhook
from database.outbox_serializer import serialize_domain_event
from seedwork.utils import generate_id
from sharding.domain.constants import DatabaseShardStatus, ShardRoutingStrategy
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import UcpOutbox
from ucp_models.sharding import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import AppSubscription

from ucp.application.dto.shard_allocation import ShardCandidateDTO
from ucp.domain.constants import LifecycleStatus, SubscriptionTier
from ucp.domain.tenant import Tenant, TenantSubscription
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort

logger = structlog.get_logger(__name__)


class SqlAlchemyTenantRepository(TenantRepositoryPort):
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _to_domain_model(
        row: DbTenant, subscriptions: list[TenantSubscription] | None = None
    ) -> Tenant:
        return Tenant(
            id=row.id,
            name=row.name,
            slug=row.slug,
            idp_tenant_id=row.idp_tenant_id,
            status=LifecycleStatus(row.status),
            created_at=row.created_at.replace(tzinfo=UTC),
            updated_at=row.updated_at.replace(tzinfo=UTC),
            subscriptions=subscriptions or [],
        )

    @staticmethod
    def _to_orm_record(tenant: Tenant) -> DbTenant:
        return DbTenant(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            idp_tenant_id=tenant.idp_tenant_id,
            status=tenant.status.value,
            created_at=tenant.created_at.replace(tzinfo=None),
            updated_at=tenant.updated_at.replace(tzinfo=None),
        )

    @staticmethod
    def _update_record_from_domain(db_tenant: DbTenant, tenant: Tenant) -> None:
        db_tenant.name = tenant.name
        db_tenant.idp_tenant_id = tenant.idp_tenant_id
        db_tenant.status = tenant.status.value
        # Slug is intentionally immutable — not updated on rename.
        # See TECHNICAL_DEBT.md: "Slug Redirect Trail for Self-Service Tenant Portals".

    async def find_by_id(self, id: str) -> Tenant | None:
        stmt = select(DbTenant).where(DbTenant.id == id, DbTenant.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        subs = await self._load_subscription_ids(row.id)
        return self._to_domain_model(row, subs)

    async def find_by_idp_tenant_id(self, idp_tenant_id: str) -> Tenant | None:
        stmt = select(DbTenant).where(
            DbTenant.idp_tenant_id == idp_tenant_id, DbTenant.deleted_at.is_(None)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if not row:
            return None

        subs = await self._load_subscription_ids(row.id)
        return self._to_domain_model(row, subs)

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
                TenantSubscription(app_id=app_id, status=LifecycleStatus(status))
            )

        tenants = []
        for row in rows:
            subs = subs_by_tenant.get(row.id, [])
            tenants.append(self._to_domain_model(row, subs))
        return tenants

    async def save(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        # 1. Save Tenant
        stmt = select(DbTenant).where(DbTenant.id == tenant.id)
        result = await self.session.execute(stmt)
        db_tenant = result.scalar_one_or_none()

        if db_tenant:
            self._update_record_from_domain(db_tenant, tenant)
        else:
            db_tenant = self._to_orm_record(tenant)
            self.session.add(db_tenant)

        # 2. Save Subscriptions (Child Entities)
        for sub in tenant.subscriptions:
            await self.upsert_app_subscription(tenant.id, sub.app_id, sub.status.value)

        # 3. Process Outbox Events (Domain Events)
        self._flush_events(tenant, idempotency_key)

    async def insert_if_slug_available(
        self, tenant: Tenant, idempotency_key: str | None = None
    ) -> bool:
        stmt = (
            insert(DbTenant)
            .values(
                id=tenant.id,
                name=tenant.name,
                slug=tenant.slug,
                idp_tenant_id=tenant.idp_tenant_id,
                status=tenant.status.value,
                created_at=tenant.created_at.replace(tzinfo=None),
                updated_at=tenant.updated_at.replace(tzinfo=None),
            )
            .on_conflict_do_nothing(index_elements=[DbTenant.slug])
            .returning(DbTenant.id)
        )
        async with intercept_db_errors():
            result = await self.session.execute(stmt)
        inserted_id = result.scalar_one_or_none()
        if inserted_id is None:
            return False

        for sub in tenant.subscriptions:
            await self.upsert_app_subscription(tenant.id, sub.app_id, sub.status.value)
        self._flush_events(tenant, idempotency_key)
        return True

    def _flush_events(self, tenant: Tenant, idempotency_key: str | None = None) -> None:
        for index, event in enumerate(tenant.domain_events):
            outbox_id = generate_id(UcpOutbox.ID_PREFIX)
            event_name = event.event_name

            final_idemp_key = (
                f"{idempotency_key}_{index}" if idempotency_key else event.idempotency_key
            )

            payload_dict = serialize_domain_event(event)
            tenant_id = event.get_routing_tenant_id()
            if tenant_id is None:
                logger.error(
                    "outbox_event_missing_tenant_id",
                    event_name=event_name,
                    event_payload=payload_dict,
                )

            outbox_event = UcpOutbox(
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
        stmt = insert(ShardRegistry).values(
            tenant_id=tenant_id,
            app_id=app_id,
            shard_id=shard_id,
            status=LifecycleStatus.ACTIVE.value,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[ShardRegistry.tenant_id, ShardRegistry.app_id],
            set_={
                ShardRegistry.shard_id: shard_id,
                ShardRegistry.status: LifecycleStatus.ACTIVE.value,
            },
        )
        await self.session.execute(stmt)

    async def upsert_app_subscription(self, tenant_id: str, app_id: str, status: str) -> None:

        stmt = insert(AppSubscription).values(
            tenant_id=tenant_id, app_id=app_id, tier=SubscriptionTier.STANDARD.value, status=status
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[AppSubscription.tenant_id, AppSubscription.app_id],
            set_={AppSubscription.status: status},
        )
        await self.session.execute(stmt)

    async def update_shard_status(self, tenant_id: str, app_id: str, status: str) -> None:
        stmt = (
            update(ShardRegistry)
            .where(
                ShardRegistry.tenant_id == tenant_id,
                ShardRegistry.app_id == app_id,
            )
            .values(status=status)
        )
        await self.session.execute(stmt)

    async def get_allocated_shard(self, tenant_id: str, app_id: str) -> str | None:
        stmt = select(ShardRegistry.shard_id).where(
            ShardRegistry.tenant_id == tenant_id,
            ShardRegistry.app_id == app_id,
            ShardRegistry.status == LifecycleStatus.ACTIVE.value,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_active_candidate_shards(
        self, app_slug: str, app_id: str
    ) -> list[ShardCandidateDTO]:
        escaped_slug = app_slug.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        slug_pattern = f"{escaped_slug}\\_%"

        stmt = (
            select(
                DatabaseShard.id,
                DatabaseShard.name,
                DatabaseShard.status,
                func.count(ShardRegistry.tenant_id).label("tenant_count"),
            )
            .outerjoin(
                ShardRegistry,
                (DatabaseShard.id == ShardRegistry.shard_id)
                & (ShardRegistry.app_id == app_id)
                & (ShardRegistry.status == LifecycleStatus.ACTIVE.value),
            )
            .where(
                DatabaseShard.status == DatabaseShardStatus.ACTIVE.value,
                DatabaseShard.routing_strategy == ShardRoutingStrategy.TENANT_REGISTRY.value,
                DatabaseShard.id.ilike(slug_pattern, escape="\\"),
            )
            .group_by(DatabaseShard.id, DatabaseShard.name, DatabaseShard.status)
            .order_by(func.count(ShardRegistry.tenant_id).asc(), DatabaseShard.id.asc())
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            ShardCandidateDTO(
                shard_id=str(row[0]),
                shard_name=str(row[1]),
                status=str(row[2]),
                current_tenant_count=int(row[3]),
            )
            for row in rows
        ]

    async def _load_subscription_ids(self, tenant_id: str) -> list[TenantSubscription]:
        stmt = select(AppSubscription.app_id, AppSubscription.status).where(
            AppSubscription.tenant_id == tenant_id
        )
        result = await self.session.execute(stmt)
        return [
            TenantSubscription(app_id=app_id, status=LifecycleStatus(status))
            for app_id, status in result.all()
        ]
