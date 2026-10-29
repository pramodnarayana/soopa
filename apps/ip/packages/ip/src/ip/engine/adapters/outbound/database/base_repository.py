"""Base SQLAlchemy repository classes for Integration Platform Control Plane and Data Plane."""

from __future__ import annotations

from ip.engine.adapters.outbound.database.models.control_plane import IpOutboxRecord
from ip.engine.adapters.outbound.database.models.data_plane import (
    IpDataPlaneOutboxRecord,
    IpTraceEventModel,
)
from outbox.domain.constants import OutboxStatus
from seedwork.utils import generate_id
from sqlalchemy.ext.asyncio import AsyncSession
from strace.adapters import HasTraceEvents, drain_trace_events

from database.outbox_serializer import serialize_domain_event
from database.repository import BaseSqlAlchemyRepository as PlatformBaseSqlAlchemyRepository
from database.repository import HasDomainEvents
from database.types import GlobalSession, TenantSession


class GlobalSqlAlchemyRepository(PlatformBaseSqlAlchemyRepository):
    """Base class for Control Plane repositories in global_db (ip schema).

    Centralizes transactional outbox draining into `ip.outbox` (`IpOutboxRecord`).
    """

    session: AsyncSession

    def __init__(self, session: AsyncSession | GlobalSession) -> None:
        info = session.info
        if (
            isinstance(info, dict)
            and "session_type" in info
            and info.get("session_type") != "global"
        ):
            raise ValueError(
                f"Expected a GlobalSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session
        self._session = session

    def _drain_events(
        self,
        aggregate: HasDomainEvents,
        default_tenant_id: str = "",
    ) -> None:
        """Extracts aggregate domain events and stages them into ip.outbox."""
        for event in aggregate.domain_events:
            outbox_id = generate_id(IpOutboxRecord.ID_PREFIX)
            tenant_id = event.get_routing_tenant_id() or default_tenant_id
            outbox_event = IpOutboxRecord(
                id=outbox_id,
                idempotency_key=event.idempotency_key,
                tenant_id=tenant_id,
                event_type=event.event_name,
                trace_id=event.get_trace_id(),
                correlation_id=event.get_correlation_id(),
                lane=event.get_processing_lane().value,
                payload=serialize_domain_event(event),
                status=OutboxStatus.PENDING,
            )
            self._session.add(outbox_event)

        aggregate.clear_domain_events()


class TenantSqlAlchemyRepository(PlatformBaseSqlAlchemyRepository):
    """Base class for Data Plane / Shard repositories in tenant shards.

    Centralizes transactional outbox draining (`IpDataPlaneOutboxRecord`) and
    trace event ledger draining (`IpTraceEventModel`).
    """

    session: AsyncSession

    def __init__(self, session: AsyncSession | TenantSession) -> None:
        info = session.info
        if (
            isinstance(info, dict)
            and "session_type" in info
            and info.get("session_type") != "tenant"
        ):
            raise ValueError(
                f"Expected a TenantSession but received a {info.get('session_type')} session. "
                "Check the UnitOfWork or dependencies injection."
            )
        self.session = session
        self._session = session

    def _drain_trace_events(self, aggregate: HasTraceEvents) -> None:
        """Drains TracedAggregateRoot trace events into the ip_trace_events ledger."""
        drain_trace_events(self._session, aggregate, IpTraceEventModel)

    def _drain_events(
        self,
        aggregate: HasDomainEvents,
        default_tenant_id: str = "",
    ) -> None:
        """Extracts aggregate domain events and stages them into the data-plane transactional outbox."""
        for event in aggregate.domain_events:
            outbox_id = generate_id(IpDataPlaneOutboxRecord.ID_PREFIX)
            tenant_id = event.get_routing_tenant_id() or default_tenant_id
            outbox_event = IpDataPlaneOutboxRecord(
                id=outbox_id,
                idempotency_key=event.idempotency_key,
                tenant_id=tenant_id,
                event_type=event.event_name,
                trace_id=event.get_trace_id(),
                correlation_id=event.get_correlation_id(),
                lane=event.get_processing_lane().value,
                payload=serialize_domain_event(event),
                status=OutboxStatus.PENDING,
            )
            self._session.add(outbox_event)

        aggregate.clear_domain_events()


__all__ = [
    "GlobalSession",
    "GlobalSqlAlchemyRepository",
    "HasTraceEvents",
    "TenantSession",
    "TenantSqlAlchemyRepository",
]
