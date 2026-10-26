"""Shared SQLAlchemy ORM mixins and event-draining utilities for distributed business traces."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from seedwork.domain.types import JsonDict
from sqlalchemy import DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, declared_attr, mapped_column

from strace.domain.models import TraceEvent


@runtime_checkable
class HasTraceEvents(Protocol):
    """Structural protocol for TracedAggregateRoot entities exposing trace_events."""

    @property
    def trace_events(self) -> Sequence[TraceEvent]: ...

    def clear_trace_events(self) -> None: ...


class OrmSessionAdder(Protocol):
    """Structural protocol for any SQLAlchemy session exposing add()."""

    def add(self, instance: object) -> None: ...


class TraceEventOrmFactoryProtocol(Protocol):
    """Callable factory protocol for constructing a TraceEvent ORM model instance."""

    def __call__(
        self,
        *,
        id: str,
        tenant_id: str,
        trace_id: str,
        correlation_id: str | None,
        event_type: str,
        actor: str,
        metadata_: JsonDict | None,
        created_at: datetime,
    ) -> object: ...


class TraceLineageMixin:
    """Core trace lineage columns shared by all stage tables (EDI and IP)."""

    @declared_attr
    def trace_id(cls) -> Mapped[str]:
        return mapped_column(String(128), nullable=False, index=True)

    @declared_attr
    def parent_trace_id(cls) -> Mapped[str | None]:
        return mapped_column(String(128), nullable=True)

    @declared_attr
    def original_trace_id(cls) -> Mapped[str | None]:
        return mapped_column(String(128), nullable=True)

    @declared_attr
    def replay_count(cls) -> Mapped[int]:
        return mapped_column(Integer, nullable=False, server_default=text("0"), default=0)


class TraceableMixin(TraceLineageMixin):
    """Standard columns for database tables participating in distributed business tracing with correlation_id."""

    @declared_attr
    def correlation_id(cls) -> Mapped[str | None]:
        return mapped_column(String(255), nullable=True, index=True)


class TraceEventMixin:
    """Standard SQLAlchemy columns for immutable trace_events audit ledger tables (EDI, IP, etc.)."""

    @declared_attr
    def tenant_id(cls) -> Mapped[str]:
        return mapped_column(String(128), nullable=False, index=True)

    @declared_attr
    def trace_id(cls) -> Mapped[str]:
        return mapped_column(String(128), nullable=False, index=True)

    @declared_attr
    def event_type(cls) -> Mapped[str]:
        return mapped_column(String(100), nullable=False)

    @declared_attr
    def actor(cls) -> Mapped[str]:
        return mapped_column(String(255), nullable=False, default="SYSTEM")

    @declared_attr
    def metadata_(cls) -> Mapped[JsonDict | None]:
        return mapped_column(JSONB, nullable=True)

    @declared_attr
    def created_at(cls) -> Mapped[datetime]:
        return mapped_column(
            DateTime(timezone=True),
            nullable=False,
            default=lambda: datetime.now(UTC),
            server_default=text("now()"),
        )


def drain_trace_events(
    session: OrmSessionAdder,
    aggregate: HasTraceEvents,
    orm_factory: TraceEventOrmFactoryProtocol,
) -> None:
    """Drains TracedAggregateRoot.trace_events into the session using the bounded context's ORM model."""
    for t_event in aggregate.trace_events:
        trace_orm = orm_factory(
            id=t_event.id,
            tenant_id=t_event.tenant_id,
            trace_id=t_event.trace_id,
            correlation_id=t_event.correlation_id,
            event_type=t_event.event_type,
            actor=t_event.actor,
            metadata_=dict(t_event.metadata) if t_event.metadata is not None else None,
            created_at=t_event.created_at,
        )
        session.add(trace_orm)
    aggregate.clear_trace_events()


__all__ = [
    "HasTraceEvents",
    "OrmSessionAdder",
    "TraceEventMixin",
    "TraceEventOrmFactoryProtocol",
    "TraceLineageMixin",
    "TraceableMixin",
    "drain_trace_events",
]
