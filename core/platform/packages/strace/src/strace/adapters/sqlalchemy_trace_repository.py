"""Centralized SQLAlchemy repository for trace events, root lineage resolution, and correlation search."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from database.repository import BaseSqlAlchemyRepository
from sqlalchemy import ColumnElement, SQLColumnExpression, String, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, Mapped, declared_attr, mapped_column

from strace.adapters.orm import TraceableMixin, TraceEventMixin, TraceLineageMixin
from strace.domain.enums import TraceStatus
from strace.domain.models import (
    TraceEvent,
    TraceLineageItemDTO,
    TraceStageAttemptRow,
    aggregate_trace_lineage_attempts,
)
from strace.ports.trace_repository_port import TraceRepositoryPort


class TenantTraceLineageOrmModel(TraceLineageMixin):
    """Base mixin for tenant-scoped SQLAlchemy ORM models with trace lineage columns."""

    @declared_attr
    def tenant_id(cls) -> Mapped[str]:
        return mapped_column(String(128), nullable=False)


class TenantTraceableOrmModel(TenantTraceLineageOrmModel, TraceableMixin):
    """Base mixin for tenant-scoped SQLAlchemy ORM models participating in distributed tracing with correlation_id."""


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
        status: TraceStatus | None = None,
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
    static_status: TraceStatus | None = None

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

    def _matches_static_status(self, status: TraceStatus) -> bool:
        if self.status_col is not None:
            return True
        return self.static_status is not None and self.static_status == status

    async def list_recent_attempts(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        limit: int,
        status: TraceStatus | None = None,
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
                stmt = stmt.where(self.status_col == status.value)
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


class SqlAlchemyTraceRepository(
    BaseSqlAlchemyRepository,
    TraceRepositoryPort,
):
    """Centralized SQLAlchemy repository for trace events, lineage trees, and correlation search across apps."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        event_spec: TraceEventSpecPort | None = None,
        stage_specs: Sequence[TraceStageSpecPort] = (),
    ) -> None:
        super().__init__(session)
        self._session = session
        self._event_spec = event_spec
        self._stage_specs = tuple(stage_specs)

    async def list_trace_events(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> list[TraceEvent]:
        if self._event_spec is None:
            return []
        return await self._event_spec.list_by_trace_id(
            self._session,
            tenant_id=tenant_id,
            trace_id=trace_id,
        )

    async def save_trace_event(
        self,
        event: TraceEvent,
    ) -> None:
        if self._event_spec is None:
            return
        self._session.add(self._event_spec.to_orm(event))
        await self._session.flush()

    async def save_all_trace_events(
        self,
        events: Sequence[TraceEvent],
    ) -> None:
        if self._event_spec is None or not events:
            return
        for event in events:
            self._session.add(self._event_spec.to_orm(event))
        await self._session.flush()

    async def resolve_root_trace_id(
        self,
        tenant_id: str,
        trace_id: str,
        stage_models_deepest_first: Sequence[type[TenantTraceLineageOrmModel]] | None = None,
    ) -> str:
        """Resolves the root original_trace_id across an ordered sequence of stage ORM models."""
        models = (
            stage_models_deepest_first
            if stage_models_deepest_first is not None
            else tuple(spec.get_model_cls() for spec in reversed(self._stage_specs))
        )
        for model_cls in models:
            stmt = (
                select(model_cls)
                .where(
                    model_cls.tenant_id == tenant_id,
                    model_cls.trace_id == trace_id,
                )
                .limit(1)
            )
            res = await self._session.execute(stmt)
            row = res.scalars().first()
            if row is not None and row.original_trace_id:
                return str(row.original_trace_id)
        return trace_id

    async def fetch_lineage_family_rows[TOrm: TenantTraceLineageOrmModel, TCol](
        self,
        model_cls: type[TOrm],
        *,
        tenant_id: str,
        root_trace_id: str,
        order_by_col: ColumnElement[TCol],
    ) -> list[TOrm]:
        """Fetches all ORM rows in a stage table belonging to root_trace_id's replay lineage family."""
        stmt = (
            select(model_cls)
            .where(
                model_cls.tenant_id == tenant_id,
                or_(
                    model_cls.trace_id == root_trace_id,
                    model_cls.original_trace_id == root_trace_id,
                ),
            )
            .order_by(order_by_col)
        )
        res = await self._session.execute(stmt)
        return list(res.scalars().all())

    async def get_trace_lineage(
        self,
        tenant_id: str,
        trace_id: str,
    ) -> list[TraceLineageItemDTO]:
        if not self._stage_specs:
            return []
        root_trace_id = await self.resolve_root_trace_id(tenant_id, trace_id)
        stage_batches: list[Sequence[TraceStageAttemptRow]] = []
        for spec in self._stage_specs:
            attempts = await spec.fetch_lineage_attempts(
                self._session,
                tenant_id=tenant_id,
                root_trace_id=root_trace_id,
            )
            stage_batches.append(attempts)

        items = aggregate_trace_lineage_attempts(
            stage_batches_in_pipeline_order=tuple(stage_batches),
            fallback_root_trace_id=root_trace_id,
        )
        return sorted(
            items,
            key=lambda item: (item.replay_count, str(item.created_at or "")),
        )

    async def find_traces_by_correlation_id(
        self,
        tenant_id: str,
        correlation_id: str,
        *,
        limit: int = 50,
    ) -> list[TraceLineageItemDTO]:
        if not self._stage_specs:
            return []
        stage_batches: list[Sequence[TraceStageAttemptRow]] = []
        for spec in self._stage_specs:
            attempts = await spec.find_correlation_attempts(
                self._session,
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                limit=limit,
            )
            stage_batches.append(attempts)

        items = aggregate_trace_lineage_attempts(
            stage_batches_in_pipeline_order=tuple(stage_batches),
        )
        sorted_items = sorted(
            items,
            key=lambda item: str(item.created_at or ""),
            reverse=True,
        )
        return sorted_items[:limit]

    async def list_recent_traces(
        self,
        tenant_id: str,
        *,
        status: TraceStatus | None = None,
        min_replay_count: int | None = None,
        limit: int = 50,
    ) -> list[TraceLineageItemDTO]:
        if not self._stage_specs:
            return []
        candidate_trace_ids: list[str] = []
        seen_trace_ids: set[str] = set()
        for idx, spec in enumerate(self._stage_specs):
            downstream_models = tuple(ds.get_model_cls() for ds in self._stage_specs[idx + 1 :])
            attempts = await spec.list_recent_attempts(
                self._session,
                tenant_id=tenant_id,
                limit=limit,
                status=status,
                min_replay_count=min_replay_count,
                downstream_models=downstream_models,
            )
            for attempt in attempts:
                if attempt.trace_id not in seen_trace_ids:
                    seen_trace_ids.add(attempt.trace_id)
                    candidate_trace_ids.append(attempt.trace_id)

        if not candidate_trace_ids:
            return []

        stage_batches: list[Sequence[TraceStageAttemptRow]] = []
        for spec in self._stage_specs:
            hydrated = await spec.fetch_attempts_for_trace_ids(
                self._session,
                tenant_id=tenant_id,
                trace_ids=candidate_trace_ids,
            )
            stage_batches.append(hydrated)

        items = aggregate_trace_lineage_attempts(
            stage_batches_in_pipeline_order=tuple(stage_batches),
        )
        filtered = [
            item
            for item in items
            if (status is None or str(item.status) == status.value)
            and (min_replay_count is None or item.replay_count >= min_replay_count)
        ]
        sorted_items = sorted(
            filtered,
            key=lambda item: str(item.created_at or ""),
            reverse=True,
        )
        return sorted_items[:limit]


BaseSqlAlchemyTraceRepository = SqlAlchemyTraceRepository

__all__ = [
    "BaseSqlAlchemyTraceRepository",
    "SqlAlchemyTraceRepository",
    "TenantTraceLineageOrmModel",
    "TenantTraceableOrmModel",
    "TraceEventSpec",
    "TraceEventSpecPort",
    "TraceStageSpec",
    "TraceStageSpecPort",
]
