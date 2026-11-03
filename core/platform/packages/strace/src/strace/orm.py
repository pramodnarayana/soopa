"""Shared SQLAlchemy ORM mixins, declarative stage specifications, and event-draining utilities for distributed business traces."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from seedwork.domain.types import JsonDict
from sqlalchemy import (
    DateTime,
    Integer,
    SQLColumnExpression,
    String,
    exists,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, Mapped, declared_attr, mapped_column

from strace.domain.enums import TraceStatus
from strace.domain.lineage import TraceStageAttemptRow
from strace.domain.trace_event import TraceEvent


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


class TenantTraceLineageOrmModel(TraceLineageMixin):
    """Base mixin for tenant-scoped SQLAlchemy ORM models with trace lineage columns."""

    @declared_attr
    def tenant_id(cls) -> Mapped[str]:
        return mapped_column(String(128), nullable=False)


class TenantTraceableOrmModel(TenantTraceLineageOrmModel, TraceableMixin):
    """Base mixin for tenant-scoped SQLAlchemy ORM models participating in distributed tracing with correlation_id."""


class TraceEventMixin:
    """Standard SQLAlchemy columns for immutable trace_events audit ledger tables (EDI, IP, etc.)."""

    @declared_attr
    def id(cls) -> Mapped[str]:
        return mapped_column(String(128), primary_key=True)

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


class TraceEventSpecPort(Protocol):
    """Polymorphic IoC port for querying and persisting a bounded context's TraceEvent ORM model."""

    async def list_by_trace_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        trace_id: str,
    ) -> list[TraceEvent]: ...

    def to_orm(self, event: TraceEvent) -> object: ...


@dataclass(frozen=True, kw_only=True)
class TraceEventSpec[TEventOrm: TraceEventMixin](TraceEventSpecPort):
    """Strongly-typed declarative specification for a bounded context's trace_events ORM table."""

    model_cls: type[TEventOrm]
    to_domain_fn: Callable[[TEventOrm], TraceEvent]
    to_orm_fn: Callable[[TraceEvent], TEventOrm]

    async def list_by_trace_id(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        trace_id: str,
    ) -> list[TraceEvent]:
        stmt = (
            select(self.model_cls)
            .where(
                self.model_cls.tenant_id == tenant_id,
                self.model_cls.trace_id == trace_id,
            )
            .order_by(self.model_cls.created_at.asc())
        )
        res = await session.execute(stmt)
        return [self.to_domain_fn(row) for row in res.scalars().all()]

    def to_orm(self, event: TraceEvent) -> TEventOrm:
        return self.to_orm_fn(event)


class TraceStageSpecPort(Protocol):
    """Polymorphic IoC port for querying a pipeline stage table in trace lineage and correlation lookups."""

    def get_model_cls(self) -> type[TenantTraceLineageOrmModel]: ...

    async def fetch_lineage_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        root_trace_id: str,
    ) -> list[TraceStageAttemptRow]: ...

    async def find_correlation_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        correlation_id: str,
        limit: int,
    ) -> list[TraceStageAttemptRow]: ...

    async def fetch_attempts_for_trace_ids(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        trace_ids: Sequence[str],
    ) -> list[TraceStageAttemptRow]: ...

    async def list_recent_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        limit: int,
        status: TraceStatus | str | None = None,
        min_replay_count: int | None = None,
        downstream_models: Sequence[type[TenantTraceLineageOrmModel]] = (),
    ) -> list[TraceStageAttemptRow]: ...


@dataclass(frozen=True, kw_only=True)
class TraceStageSpec[TOrm: TenantTraceLineageOrmModel](TraceStageSpecPort):
    """Strongly-typed declarative specification for a stage ORM table participating in trace lineage."""

    model_cls: type[TOrm]
    timestamp_col: InstrumentedAttribute[datetime]
    to_attempt_row: Callable[[TOrm], TraceStageAttemptRow]
    correlation_cols: tuple[InstrumentedAttribute[str | None], ...] = ()
    status_col: SQLColumnExpression[str] | None = None
    static_status: TraceStatus | str | None = None

    def get_model_cls(self) -> type[TOrm]:
        return self.model_cls

    async def fetch_lineage_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        root_trace_id: str,
    ) -> list[TraceStageAttemptRow]:
        stmt = (
            select(self.model_cls)
            .where(
                self.model_cls.tenant_id == tenant_id,
                or_(
                    self.model_cls.trace_id == root_trace_id,
                    self.model_cls.original_trace_id == root_trace_id,
                ),
            )
            .order_by(self.timestamp_col.asc())
        )
        res = await session.execute(stmt)
        return [self.to_attempt_row(row) for row in res.scalars().all()]

    async def fetch_attempts_for_trace_ids(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        trace_ids: Sequence[str],
    ) -> list[TraceStageAttemptRow]:
        if not trace_ids:
            return []
        stmt = (
            select(self.model_cls)
            .where(
                self.model_cls.tenant_id == tenant_id,
                self.model_cls.trace_id.in_(trace_ids),
            )
            .order_by(self.timestamp_col.asc())
        )
        res = await session.execute(stmt)
        return [self.to_attempt_row(row) for row in res.scalars().all()]

    async def find_correlation_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        correlation_id: str,
        limit: int,
    ) -> list[TraceStageAttemptRow]:
        if not self.correlation_cols:
            return []
        corr_predicate = or_(*(col == correlation_id for col in self.correlation_cols))
        stmt = (
            select(self.model_cls)
            .where(
                self.model_cls.tenant_id == tenant_id,
                corr_predicate,
            )
            .order_by(self.timestamp_col.desc())
            .limit(limit)
        )
        res = await session.execute(stmt)
        return [self.to_attempt_row(row) for row in res.scalars().all()]

    def _matches_static_status(self, status: TraceStatus | str) -> bool:
        if self.status_col is not None:
            return True
        return self.static_status is not None and str(self.static_status) == str(status)

    async def list_recent_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        limit: int,
        status: TraceStatus | str | None = None,
        min_replay_count: int | None = None,
        downstream_models: Sequence[type[TenantTraceLineageOrmModel]] = (),
    ) -> list[TraceStageAttemptRow]:
        if status is not None and not self._matches_static_status(status):
            return []
        stmt = select(self.model_cls).where(self.model_cls.tenant_id == tenant_id)
        if min_replay_count is not None:
            stmt = stmt.where(self.model_cls.replay_count >= min_replay_count)
        if status is not None:
            if self.status_col is not None:
                stmt = stmt.where(self.status_col == str(status))
            for downstream_cls in downstream_models:
                stmt = stmt.where(
                    ~exists(
                        select(1).where(
                            downstream_cls.tenant_id == self.model_cls.tenant_id,
                            downstream_cls.trace_id == self.model_cls.trace_id,
                        )
                    )
                )
        stmt = stmt.order_by(self.timestamp_col.desc()).limit(limit)
        res = await session.execute(stmt)
        return [self.to_attempt_row(row) for row in res.scalars().all()]


__all__ = [
    "HasTraceEvents",
    "OrmSessionAdder",
    "TenantTraceLineageOrmModel",
    "TenantTraceableOrmModel",
    "TraceEventMixin",
    "TraceEventOrmFactoryProtocol",
    "TraceEventSpec",
    "TraceEventSpecPort",
    "TraceLineageMixin",
    "TraceStageSpec",
    "TraceStageSpecPort",
    "TraceableMixin",
    "drain_trace_events",
]
