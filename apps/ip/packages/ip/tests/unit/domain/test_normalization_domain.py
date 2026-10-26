"""Unit tests for L3 normalization domain models and value objects."""

from dataclasses import dataclass

from ip.engine.domain.enums import (
    MappingMode,
    NormalizationOutcome,
    NormalizationRejectionReason,
    PendingReferenceStatus,
    RuleSeverity,
)
from ip.engine.domain.normalization import (
    CanonicalDraft,
    CanonicalEntityDefinition,
    MappingBinding,
    MappingContext,
    MappingResult,
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
    ReplicaSnapshot,
    SourceReference,
)
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


def test_mapping_result_empty_defaults() -> None:
    res = MappingResult()
    assert res.drafts == ()
    assert res.rejections == ()


def test_mapping_context_properties() -> None:
    ctx = MappingContext(
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


def test_mapping_binding_factory() -> None:
    binding = MappingBinding.create(
        tenant_id="tenant_123",
        connection_id="conn_456",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
        mode=MappingMode.ACTIVE,
        shadow_mapping_version=2,
    )
    assert binding.id.startswith("ip_bind_")
    assert binding.tenant_id == "tenant_123"
    assert binding.connection_id == "conn_456"
    assert binding.stream == "readings"
    assert binding.mapping_id == "energy.ami_meter_reading"
    assert binding.mapping_version == 1
    assert binding.mode == MappingMode.ACTIVE
    assert binding.shadow_mapping_version == 2


def test_normalization_ledger_entry_factory() -> None:
    entry = NormalizationLedgerEntry.create(
        tenant_id="tenant_123",
        replica_record_id="rep_999",
        replica_version=2,
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
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
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
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
