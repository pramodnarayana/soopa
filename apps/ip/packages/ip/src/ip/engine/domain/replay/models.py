"""Domain models for app-owned IP replay audit ledgers (schema ip)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from replay.domain.audit_mixin import ReplayAuditMixin
from replay.domain.enums import ReplayStage, ReplayStatus, ReplayTargetType
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id


@dataclass(kw_only=True)
class IpReplayLedgerRecord(ReplayAuditMixin):
    """Immutable audit record for a replay execution on `ip.ip_replay_ledger`."""

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        idempotency_key: str,
        target_type: ReplayTargetType,
        target_id: str,
        target_stage: ReplayStage,
        trace_id: str,
        parent_trace_id: str,
        actor: str,
        reason: str,
        payload_override: JsonDict | None = None,
        original_trace_id: str | None = None,
        correlation_id: str | None = None,
        affected_records: int = 0,
    ) -> IpReplayLedgerRecord:
        return cls(
            id=generate_id("rpl"),
            tenant_id=tenant_id,
            idempotency_key=idempotency_key,
            target_type=target_type,
            target_id=target_id,
            target_stage=target_stage,
            trace_id=trace_id,
            parent_trace_id=parent_trace_id,
            original_trace_id=original_trace_id,
            correlation_id=correlation_id,
            actor=actor,
            reason=reason,
            payload_override=payload_override,
            affected_records=affected_records,
            status=ReplayStatus.IN_FLIGHT,
            error_message=None,
            created_at=datetime.now(UTC),
            completed_at=None,
        )

    def mark_completed(self, affected_records: int | None = None) -> None:
        self.status = ReplayStatus.COMPLETED
        if affected_records is not None:
            self.affected_records = affected_records
        self.completed_at = datetime.now(UTC)

    def mark_failed(self, error_message: str) -> None:
        self.status = ReplayStatus.FAILED
        self.error_message = error_message
        self.completed_at = datetime.now(UTC)


IpReplayAuditRecord = IpReplayLedgerRecord
