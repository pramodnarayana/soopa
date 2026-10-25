"""SQLAlchemy ORM models for the 12 Hatchet-inspired Durable Workflow Engine tables."""

from __future__ import annotations

from datetime import datetime

from seedwork.domain.types import JsonDict
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, registry

WorkflowRegistry = registry()


class WorkflowBase(DeclarativeBase):
    """Declarative base for all Durable Workflow Engine tables."""

    registry = WorkflowRegistry


class WorkflowRunModel(WorkflowBase):
    """Narrow workflow_runs table (`v1_dag`) without inline payloads."""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        PrimaryKeyConstraint("id", "created_at"),
        Index(
            "idx_wf_runs_active_conc",
            "tenant_id",
            "workflow_id",
            "concurrency_key",
            postgresql_where=text("status IN ('QUEUED', 'RUNNING', 'WAITING')"),
        ),
        Index("idx_wf_runs_trace", "tenant_id", "trace_id"),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    concurrency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkflowStepRunModel(WorkflowBase):
    """Narrow workflow_step_runs table (`v1_task`) with Hatchet 3-counter retries."""

    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        PrimaryKeyConstraint("id", "created_at"),
        Index(
            "uq_wf_step_run_node",
            "run_id",
            "node_key",
            "created_at",
            unique=True,
        ),
        Index("idx_wf_step_runs_run", "tenant_id", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    run_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    app_retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    internal_retry_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkflowActiveLeaseModel(WorkflowBase):
    """Unpartitioned active leases table (`v1_task_runtime`)."""

    __tablename__ = "workflow_active_leases"
    __table_args__ = (
        PrimaryKeyConstraint("step_run_id", "step_created_at", "retry_count"),
        Index("idx_wf_active_leases_expiry", "lease_expires_at"),
        Index("idx_wf_active_leases_timeout", "timeout_at"),
    )

    step_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    timeout_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    evicted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkflowStepAttemptModel(WorkflowBase):
    """Immutable audit log of step attempts (`workflow_step_attempts`)."""

    __tablename__ = "workflow_step_attempts"
    __table_args__ = (
        PrimaryKeyConstraint("id", "started_at"),
        Index("idx_wf_step_attempts_step", "tenant_id", "step_run_id"),
    )

    id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    app_retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    internal_retry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    is_app_error: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class WorkflowPayloadModel(WorkflowBase):
    """Decoupled payload store (`v1_payload`) with zero-copy reference and external S3 pointer support."""

    __tablename__ = "workflow_payloads"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "owner_id", "owner_created_at", "payload_type"),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    payload_type: Mapped[str] = mapped_column(String(32), nullable=False)
    location: Mapped[str] = mapped_column(String(16), nullable=False)
    inline_content: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    external_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payload_reference_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    payload_reference_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WorkflowIdempotencyKeyModel(WorkflowBase):
    """Unpartitioned cross-partition idempotency table (`v1_idempotency_key`)."""

    __tablename__ = "workflow_idempotency_keys"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "workflow_id", "key"),
        Index("idx_wf_idempotency_expires", "expires_at"),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_id: Mapped[str] = mapped_column(String(128), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    claimed_by_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    eviction_policy: Mapped[str] = mapped_column(
        String(32), nullable=False, default="TTL"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WorkflowMatchModel(WorkflowBase):
    """Hatchet v1 CNF condition match header (`v1_match`)."""

    __tablename__ = "workflow_matches"
    __table_args__ = (
        Index("idx_wf_matches_run", "tenant_id", "run_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    node_key: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    existing_data: Mapped[JsonDict] = mapped_column(JSONB, nullable=False, default=dict)
    is_satisfied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WorkflowMatchConditionModel(WorkflowBase):
    """Hatchet v1 CNF condition clause (`v1_match_condition`)."""

    __tablename__ = "workflow_match_conditions"
    __table_args__ = (
        PrimaryKeyConstraint("match_id", "id"),
        Index(
            "idx_wf_match_cond_event",
            "tenant_id",
            "condition_kind",
            "event_key",
            "event_resource_hint",
            postgresql_where=text("NOT is_satisfied"),
        ),
        Index(
            "idx_wf_match_cond_timeout",
            "timeout_at",
            postgresql_where=text("NOT is_satisfied AND timeout_at IS NOT NULL"),
        ),
    )

    match_id: Mapped[str] = mapped_column(String(64), nullable=False)
    id: Mapped[str] = mapped_column(String(64), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    or_group_id: Mapped[str] = mapped_column(String(64), nullable=False)
    condition_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    event_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_resource_hint: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    predicate_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    readable_data_key: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    is_satisfied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    matched_data: Mapped[JsonDict | None] = mapped_column(JSONB, nullable=True)
    timeout_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WorkflowQueueItemModel(WorkflowBase):
    """Hot work queue table (`workflow_queue_items`)."""

    __tablename__ = "workflow_queue_items"
    __table_args__ = (
        Index(
            "idx_wf_queue_poll",
            "queue_name",
            "available_at",
            "tenant_id",
            "priority",
            "id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    item_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    queue_name: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    enqueued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    concurrency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rate_limit_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rate_limit_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class WorkflowPausedQueueItemModel(WorkflowBase):
    """Parked rate-limited queue items (`workflow_paused_queue_items`)."""

    __tablename__ = "workflow_paused_queue_items"
    __table_args__ = (
        Index(
            "idx_wf_paused_queue_unpause",
            "requeue_after",
            "tenant_id",
            "rate_limit_key",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rate_limit_key: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queue_name: Mapped[str] = mapped_column(String(64), nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    requeue_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    concurrency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rate_limit_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WorkflowQueueCursorModel(WorkflowBase):
    """Per-queue fairness cursor (`workflow_queue_cursors`)."""

    __tablename__ = "workflow_queue_cursors"

    queue_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    last_serviced_tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    min_unprocessed_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WorkflowConcurrencySlotModel(WorkflowBase):
    """Unified Hatchet v1 concurrency slots (`v1_concurrency_slot`)."""

    __tablename__ = "workflow_concurrency_slots"
    __table_args__ = (
        PrimaryKeyConstraint(
            "sort_id",
            "tenant_id",
            "strategy_id",
            "step_run_id",
            "step_created_at",
            "retry_count",
        ),
        Index(
            "idx_wf_conc_slots_eval",
            "tenant_id",
            "strategy_id",
            "concurrency_key",
            "is_filled",
            "sort_id",
        ),
    )

    sort_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    strategy_id: Mapped[str] = mapped_column(String(64), nullable=False)
    concurrency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_run_id: Mapped[str] = mapped_column(String(64), nullable=False)
    step_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=2)
    is_filled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    next_strategy_ids: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    queue_name: Mapped[str] = mapped_column(
        String(64), nullable=False, default="default"
    )
    rate_limit_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    rate_limit_units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    acquired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class WorkflowRateLimitBucketModel(WorkflowBase):
    """Token-bucket rate limit state (`workflow_rate_limit_buckets`)."""

    __tablename__ = "workflow_rate_limit_buckets"
    __table_args__ = (
        PrimaryKeyConstraint("tenant_id", "rate_limit_key"),
    )

    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rate_limit_key: Mapped[str] = mapped_column(String(255), nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    refill_per_second: Mapped[float] = mapped_column(Float, nullable=False)
    tokens: Mapped[float] = mapped_column(Float, nullable=False)
    refilled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    paused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paused_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = [
    "WorkflowActiveLeaseModel",
    "WorkflowBase",
    "WorkflowConcurrencySlotModel",
    "WorkflowIdempotencyKeyModel",
    "WorkflowMatchConditionModel",
    "WorkflowMatchModel",
    "WorkflowPausedQueueItemModel",
    "WorkflowPayloadModel",
    "WorkflowQueueCursorModel",
    "WorkflowQueueItemModel",
    "WorkflowRateLimitBucketModel",
    "WorkflowRegistry",
    "WorkflowRunModel",
    "WorkflowStepAttemptModel",
    "WorkflowStepRunModel",
]
