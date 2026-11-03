"""Unit tests for L3 normalization domain models and value objects."""

from dataclasses import dataclass

from ip.engine.domain.normalization.enums import (
    CanonicalAction,
    NormalizationOutcome,
    NormalizationRejectionReason,
    PendingReferenceStatus,
    RuleSeverity,
    TransformationMode,
)
from ip.engine.domain.normalization.events import CanonicalRecordChangedEvent
from ip.engine.domain.normalization.ledger import (
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
)
from ip.engine.domain.normalization.transformation import (
    CanonicalDraft,
    CanonicalEntityDefinition,
    ReplicaSnapshot,
    SourceReference,
    Transformation,
    TransformationContext,
    TransformationResult,
)
from ip.engine.domain.trace.enums import IpTraceEventType, TraceEventStatus
from seedwork.domain.types import JsonDict


@dataclass(frozen=True)
class MockQualityRule:
    rule_code: str
    severity_level: RuleSeverity
    required_field: str

    @property
    def code(self) -> str:
        return self.rule_code

    @property
    def severity(self) -> RuleSeverity:
        return self.severity_level

    def evaluate(self, fields: JsonDict) -> str | None:
        if self.required_field not in fields or fields[self.required_field] is None:
            return f"Missing required field: {self.required_field}"
        return None


def test_canonical_draft_creation() -> None:
    ref = SourceReference(
        field_name="service_point_id",
        target_canonical_type="energy.service_point",
        target_source_id="sp_100",
    )
    draft = CanonicalDraft(
        canonical_type="energy.meter_reading",
        source_id="mr_123",
        fields={"kwh": 42.5, "meter_id": "MTR-1"},
        references=(ref,),
        extensions={"raw_flag": "A"},
    )
    assert draft.canonical_type == "energy.meter_reading"
    assert draft.source_id == "mr_123"
    assert draft.fields["kwh"] == 42.5
    assert len(draft.references) == 1
    assert draft.references[0].target_source_id == "sp_100"
    assert draft.extensions["raw_flag"] == "A"


def test_transformation_result_empty_defaults() -> None:
    res = TransformationResult()
    assert res.drafts == ()
    assert res.rejections == ()


def test_transformation_context_properties() -> None:
    ctx = TransformationContext(
        connection_id="conn_1",
        stream="meter_readings",
        tenant_id="tenant_a",
        trace_id="trc_1",
        correlation_id="corr_1",
    )
    assert ctx.connection_id == "conn_1"
    assert ctx.stream == "meter_readings"
    assert ctx.tenant_id == "tenant_a"
    assert ctx.trace_id == "trc_1"
    assert ctx.correlation_id == "corr_1"


def test_replica_snapshot_properties() -> None:
    snapshot = ReplicaSnapshot(
        id="rep_1",
        connection_id="conn_1",
        stream="devices",
        record_key="key_123",
        version=3,
        data={"serial": "SN-999"},
        is_deleted=False,
    )
    assert snapshot.id == "rep_1"
    assert snapshot.version == 3
    assert not snapshot.is_deleted
    assert snapshot.data["serial"] == "SN-999"


def test_quality_rule_evaluation() -> None:
    rule_reject = MockQualityRule(
        rule_code="QR_METER_ID",
        severity_level=RuleSeverity.REJECT,
        required_field="meter_id",
    )
    rule_flag = MockQualityRule(
        rule_code="QR_KWH",
        severity_level=RuleSeverity.FLAG,
        required_field="kwh",
    )

    entity_def = CanonicalEntityDefinition(
        canonical_type="energy.meter_reading",
        schema_version=1,
        quality_rules=(rule_reject, rule_flag),
    )

    assert entity_def.canonical_type == "energy.meter_reading"
    assert len(entity_def.quality_rules) == 2

    # Fails reject rule
    assert rule_reject.evaluate({}) == "Missing required field: meter_id"
    # Passes reject rule
    assert rule_reject.evaluate({"meter_id": "MTR-1"}) is None


def test_transformation_factory() -> None:
    transformation = Transformation.create(
        tenant_id="tenant_123",
        connection_id="conn_456",
        stream="readings",
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        mode=TransformationMode.ACTIVE,
        shadow_transformation_version=2,
    )
    assert transformation.id.startswith("ip_xfrm_")
    assert transformation.tenant_id == "tenant_123"
    assert transformation.connection_id == "conn_456"
    assert transformation.stream == "readings"
    assert transformation.transformation_id == "energy.ami_meter_reading"
    assert transformation.transformation_version == 1
    assert transformation.mode == TransformationMode.ACTIVE
    assert transformation.shadow_transformation_version == 2


def test_normalization_ledger_entry_factory() -> None:
    entry = NormalizationLedgerEntry.create(
        tenant_id="tenant_123",
        replica_record_id="rep_999",
        replica_version=2,
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        produced_canonical_refs=(("energy.meter_reading", "mr_1"),),
        outcome=NormalizationOutcome.NORMALIZED,
        trace_id="trc_abc",
        correlation_id="corr_xyz",
    )
    assert entry.id.startswith("ip_nlg_")
    assert entry.replica_record_id == "rep_999"
    assert entry.replica_version == 2
    assert entry.produced_canonical_refs == (("energy.meter_reading", "mr_1"),)
    assert entry.outcome == NormalizationOutcome.NORMALIZED
    assert entry.trace_id == "trc_abc"


def test_normalization_rejection_entry_factory() -> None:
    rej = NormalizationRejectionEntry.create(
        tenant_id="tenant_123",
        replica_record_id="rep_999",
        stream="readings",
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        reason_code=NormalizationRejectionReason.MISSING_REQUIRED_FIELD.value,
        detail="Payload missing timestamp",
        trace_id="trc_abc",
        field_path="reading_time",
    )
    assert rej.id.startswith("ip_nrj_")
    assert rej.reason_code == NormalizationRejectionReason.MISSING_REQUIRED_FIELD.value
    assert rej.field_path == "reading_time"
    assert rej.detail == "Payload missing timestamp"


def test_normalization_shadow_diff_entry_factory() -> None:
    diff = NormalizationShadowDiffEntry.create(
        tenant_id="tenant_123",
        replica_record_id="rep_999",
        candidate_version=2,
        diff_data={"kwh": {"active": 10.0, "shadow": 10.5}},
        trace_id="trc_abc",
    )
    assert diff.id.startswith("ip_sdiff_")
    assert diff.candidate_version == 2
    assert "kwh" in diff.diff_data


def test_pending_reference_entry_factory() -> None:
    pending = PendingReferenceEntry.create(
        tenant_id="tenant_123",
        source_connection_id="conn_1",
        target_canonical_type="energy.service_point",
        target_source_id="sp_100",
        referencing_canonical_type="energy.meter_reading",
        referencing_source_id="mr_1",
        referencing_field="service_point_id",
        trace_id="trc_abc",
    )
    assert pending.id.startswith("ip_pref_")
    assert pending.status == PendingReferenceStatus.PENDING
    assert pending.target_canonical_type == "energy.service_point"
    assert pending.resolved_at is None


def test_normalization_ledger_entry_traced_aggregate_transitions() -> None:
    ledger = NormalizationLedgerEntry.begin(
        tenant_id="tenant_1",
        replica_record_id="rep_10",
        replica_version=3,
        transformation_id="energy.ami_meter_reading",
        transformation_version=2,
        trace_id="trc_norm",
        correlation_id="corr_norm",
    )
    ledger.record_pending_reference(
        field_name="service_point_id",
        target_canonical_type="energy.service_point",
        target_source_id="sp_999",
    )
    ledger.record_canonical_upsert(
        connection_id="conn_1",
        canonical_type="energy.meter_reading",
        source_id="mr_10",
        changed_fields=("kwh", "meter_serial"),
    )
    ledger.record_unseen_draft_tombstone(
        connection_id="conn_1",
        canonical_type="energy.meter_reading",
        source_id="mr_old",
    )
    ledger.record_resolved_reference(
        field_name="service_point_id",
        referencing_canonical_type="energy.meter_reading",
        referencing_source_id="mr_early",
        target_id="canon_sp_999",
    )
    outcome = ledger.complete_normalization(rejections_count=0)

    assert outcome == NormalizationOutcome.NORMALIZED
    assert ledger.outcome == NormalizationOutcome.NORMALIZED
    assert ledger.produced_canonical_refs == (("energy.meter_reading", "mr_10"),)

    domain_events = [e for e in ledger.domain_events if isinstance(e, CanonicalRecordChangedEvent)]
    assert len(domain_events) == 2
    assert domain_events[0].action == CanonicalAction.UPSERT.value
    assert domain_events[0].source_id == "mr_10"
    assert domain_events[1].action == CanonicalAction.TOMBSTONE.value
    assert domain_events[1].source_id == "mr_old"

    trace_types = [t.event_type for t in ledger.trace_events]
    assert trace_types == [
        IpTraceEventType.REFERENCE_PENDING.value,
        IpTraceEventType.TOMBSTONED.value,
        IpTraceEventType.REFERENCE_RESOLVED.value,
        IpTraceEventType.NORMALIZED.value,
    ]


def test_normalization_ledger_entry_reject_and_tombstone_transitions() -> None:
    rejected = NormalizationLedgerEntry.reject_execution(
        tenant_id="tenant_1",
        replica_record_id="rep_10",
        replica_version=1,
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        reason_code=NormalizationRejectionReason.TRANSFORMER_ERROR.value,
        detail="Invalid payload",
        summary_message="Transformer execution failed: Invalid payload",
        trace_id="trc_rej",
    )
    assert rejected.outcome == NormalizationOutcome.REJECTED
    assert rejected.produced_canonical_refs == ()
    assert len(rejected.trace_events) == 1
    assert rejected.trace_events[0].event_type == IpTraceEventType.NORMALIZATION_REJECTED.value

    tombstoned = NormalizationLedgerEntry.begin(
        tenant_id="tenant_1",
        replica_record_id="rep_11",
        replica_version=2,
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        trace_id="trc_tomb",
    )
    tombstoned.record_canonical_tombstone(
        connection_id="conn_1",
        canonical_type="energy.meter_reading",
        source_id="mr_11",
    )
    tombstoned.complete_tombstone(tombstoned_count=1)
    assert tombstoned.outcome == NormalizationOutcome.TOMBSTONED
    assert len(tombstoned.domain_events) == 1
    assert len(tombstoned.trace_events) == 1
    assert tombstoned.trace_events[0].event_type == IpTraceEventType.TOMBSTONED.value


def test_non_ledger_normalization_trace_builders() -> None:
    transformation = Transformation.create(
        tenant_id="tenant_1",
        connection_id="conn_1",
        stream="readings",
        transformation_id="energy.ami_meter_reading",
        transformation_version=1,
        mode=TransformationMode.SHADOW,
        shadow_transformation_version=2,
    )
    stale_trace = transformation.build_skipped_stale_trace(
        replica_version=2,
        trace_id="trc_stale",
        correlation_id=None,
    )
    assert stale_trace.event_type == IpTraceEventType.SKIPPED_STALE.value
    assert stale_trace.metadata is not None
    assert stale_trace.metadata["status"] == TraceEventStatus.SUCCESS.value

    shadow_trace = transformation.build_shadow_evaluation_trace(
        replica_record_id="rep_1",
        candidate_version=2,
        drafts_count=1,
        shadow_diff_count=1,
        outcome=NormalizationOutcome.NORMALIZED,
        trace_id="trc_shd",
        correlation_id=None,
    )
    assert shadow_trace.event_type == IpTraceEventType.NORMALIZED.value

    rej = NormalizationRejectionEntry.create(
        tenant_id="tenant_1",
        replica_record_id="rep_1",
        stream="readings",
        transformation_id="energy.ami_meter_reading",
        transformation_version=2,
        reason_code=NormalizationRejectionReason.TRANSFORMER_ERROR.value,
        detail="Missing shadow transformer",
        trace_id="trc_shd_rej",
    )
    rej_trace = rej.build_rejection_trace(summary_message="Missing shadow transformer")
    assert rej_trace.event_type == IpTraceEventType.NORMALIZATION_REJECTED.value
