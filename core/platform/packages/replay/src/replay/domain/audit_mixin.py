"""Replay audit ledger mixin for app-owned relational tables (e.g. ip_replay_ledger)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from replay.domain.enums import ReplayStage, ReplayStatus, ReplayTargetType
from seedwork.domain.types import JsonDict


@dataclass(kw_only=True)
class ReplayAuditMixin:
    """Standard fields for app-owned replay audit ledger tables."""

    id: str
    tenant_id: str
    idempotency_key: str
    target_type: ReplayTargetType
    target_id: str
    target_stage: ReplayStage
    trace_id: str
    parent_trace_id: str
    actor: str
    reason: str
    affected_records: int
    status: ReplayStatus
    original_trace_id: str | None = None
    correlation_id: str | None = None
    payload_override: JsonDict | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
