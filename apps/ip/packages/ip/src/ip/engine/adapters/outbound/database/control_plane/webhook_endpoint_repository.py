"""SQLAlchemy repository adapter for WebhookEndpoint aggregate roots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.base_repository import GlobalSqlAlchemyRepository
from ip.engine.adapters.outbound.database.models.control_plane import (
    WebhookEndpointRecord,
    WebhookEventRouteRecord,
)
from ip.engine.domain.webhook.endpoint import WebhookEndpoint
from ip.engine.domain.webhook.enums import PayloadSemantic, VerificationStrategy
from ip.engine.domain.webhook.route import WebhookEventRoute
from ip.engine.ports.outbound.webhook_endpoint_repository_port import (
    WebhookEndpointRepositoryPort,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


class SqlAlchemyWebhookEndpointRepository(
    GlobalSqlAlchemyRepository, WebhookEndpointRepositoryPort
):
    """PostgreSQL SQLAlchemy implementation of WebhookEndpointRepositoryPort."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @staticmethod
    def _parse_iso(iso_str: str | None) -> datetime | None:
        if not iso_str:
            return None
        return datetime.fromisoformat(iso_str)

    @staticmethod
    def _format_iso(dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.isoformat()

    @classmethod
    def _route_to_domain_model(cls, record: WebhookEventRouteRecord) -> WebhookEventRoute:
        """Strict property-by-property mapper for WebhookEventRoute."""
        return WebhookEventRoute(
            id=record.id,
            endpoint_id=record.endpoint_id,
            event_pattern=record.event_pattern,
            payload_semantic=PayloadSemantic(record.payload_semantic),
            target_pipeline_or_workflow_id=record.target_pipeline_or_workflow_id,
            description=record.description,
            priority=record.priority,
            is_active=record.is_active,
            created_at=cls._format_iso(record.created_at) or "",
        )

    @classmethod
    def _to_domain_model(cls, record: WebhookEndpointRecord) -> WebhookEndpoint:
        """Strict property-by-property mapper from ORM record to Domain Aggregate Root."""
        routes = [cls._route_to_domain_model(r) for r in record.routes]
        return WebhookEndpoint(
            id=record.id,
            tenant_id=record.tenant_id,
            endpoint_slug=record.endpoint_slug,
            name=record.name,
            description=record.description,
            verification_strategy=VerificationStrategy(record.verification_strategy),
            primary_secret_hash=record.primary_secret_hash,
            secondary_secret_hash=record.secondary_secret_hash,
            secret_rotated_at=cls._format_iso(record.secret_rotated_at),
            bound_connection_id=record.bound_connection_id,
            is_active=record.is_active,
            event_routes=routes,
            created_at=cls._format_iso(record.created_at) or "",
            updated_at=cls._format_iso(record.updated_at) or "",
        )

    async def get_by_id(self, endpoint_id: str) -> WebhookEndpoint | None:
        stmt = (
            select(WebhookEndpointRecord)
            .options(selectinload(WebhookEndpointRecord.routes))
            .where(WebhookEndpointRecord.id == endpoint_id)
        )
        res = await self._session.execute(stmt)
        record = res.scalar_one_or_none()
        return self._to_domain_model(record) if record else None

    async def get_by_slug(self, tenant_id: str, endpoint_slug: str) -> WebhookEndpoint | None:
        stmt = (
            select(WebhookEndpointRecord)
            .options(selectinload(WebhookEndpointRecord.routes))
            .where(
                WebhookEndpointRecord.tenant_id == tenant_id,
                WebhookEndpointRecord.endpoint_slug == endpoint_slug.strip().lower(),
            )
        )
        res = await self._session.execute(stmt)
        record = res.scalar_one_or_none()
        return self._to_domain_model(record) if record else None

    async def list_by_tenant(self, tenant_id: str) -> Sequence[WebhookEndpoint]:
        stmt = (
            select(WebhookEndpointRecord)
            .options(selectinload(WebhookEndpointRecord.routes))
            .where(WebhookEndpointRecord.tenant_id == tenant_id)
            .order_by(WebhookEndpointRecord.created_at.asc())
        )
        res = await self._session.execute(stmt)
        records = res.scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def save(self, endpoint: WebhookEndpoint) -> None:
        """Saves endpoint aggregate root and synchronizes child routes."""
        stmt = (
            select(WebhookEndpointRecord)
            .options(selectinload(WebhookEndpointRecord.routes))
            .where(WebhookEndpointRecord.id == endpoint.id)
        )
        res = await self._session.execute(stmt)
        rec = res.scalar_one_or_none()

        created_dt = self._parse_iso(endpoint.created_at) or datetime.now(UTC)
        updated_dt = self._parse_iso(endpoint.updated_at) or datetime.now(UTC)
        rotated_dt = self._parse_iso(endpoint.secret_rotated_at)

        if rec is None:
            rec = WebhookEndpointRecord(
                id=endpoint.id,
                tenant_id=endpoint.tenant_id,
                endpoint_slug=endpoint.endpoint_slug,
                name=endpoint.name,
                description=endpoint.description,
                verification_strategy=endpoint.verification_strategy.value,
                primary_secret_hash=endpoint.primary_secret_hash,
                secondary_secret_hash=endpoint.secondary_secret_hash,
                secret_rotated_at=rotated_dt,
                bound_connection_id=endpoint.bound_connection_id,
                is_active=endpoint.is_active,
                created_at=created_dt,
                updated_at=updated_dt,
            )
            self._session.add(rec)
        else:
            rec.name = endpoint.name
            rec.description = endpoint.description
            rec.verification_strategy = endpoint.verification_strategy.value
            rec.primary_secret_hash = endpoint.primary_secret_hash
            rec.secondary_secret_hash = endpoint.secondary_secret_hash
            rec.secret_rotated_at = rotated_dt
            rec.bound_connection_id = endpoint.bound_connection_id
            rec.is_active = endpoint.is_active
            rec.updated_at = updated_dt

        # Synchronize child routes
        existing_route_map = {r.id: r for r in rec.routes}
        target_route_ids = {r.id for r in endpoint.event_routes}

        # Remove deleted routes
        for route_id, route_rec in list(existing_route_map.items()):
            if route_id not in target_route_ids:
                rec.routes.remove(route_rec)

        # Add or update routes
        for dom_route in endpoint.event_routes:
            route_created = self._parse_iso(dom_route.created_at) or datetime.now(UTC)
            if dom_route.id in existing_route_map:
                existing_r = existing_route_map[dom_route.id]
                existing_r.event_pattern = dom_route.event_pattern
                existing_r.payload_semantic = dom_route.payload_semantic.value
                existing_r.target_pipeline_or_workflow_id = dom_route.target_pipeline_or_workflow_id
                existing_r.description = dom_route.description
                existing_r.priority = dom_route.priority
                existing_r.is_active = dom_route.is_active
            else:
                new_r = WebhookEventRouteRecord(
                    id=dom_route.id,
                    endpoint_id=endpoint.id,
                    event_pattern=dom_route.event_pattern,
                    payload_semantic=dom_route.payload_semantic.value,
                    target_pipeline_or_workflow_id=dom_route.target_pipeline_or_workflow_id,
                    description=dom_route.description,
                    priority=dom_route.priority,
                    is_active=dom_route.is_active,
                    created_at=route_created,
                )
                rec.routes.append(new_r)

        self._drain_events(endpoint, default_tenant_id=endpoint.tenant_id)
        await self._session.flush()

    async def delete(self, endpoint_id: str) -> None:
        stmt = delete(WebhookEndpointRecord).where(WebhookEndpointRecord.id == endpoint_id)
        await self._session.execute(stmt)
        await self._session.flush()
