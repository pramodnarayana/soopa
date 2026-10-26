"""Pure zero-mock Data Mapper unit tests for Layer 3 Normalization SQLAlchemy repositories."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.adapters.outbound.database.control_plane.mapping_binding_repository import (
    SqlAlchemyMappingBindingRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_ledger_repository import (
    SqlAlchemyNormalizationLedgerRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_rejection_repository import (
    SqlAlchemyNormalizationRejectionRepository,
)
from ip.engine.adapters.outbound.database.data_plane.pending_reference_repository import (
    SqlAlchemyPendingReferenceRepository,
)
from ip.engine.domain.enums import (
    MappingMode,
    NormalizationOutcome,
    NormalizationRejectionReason,
    PendingReferenceStatus,
)
from ip.engine.domain.normalization import (
    MappingBinding,
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
)


def test_mapping_binding_data_mappers_roundtrip_and_update() -> None:
    binding = MappingBinding.create(
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="orders",
        mapping_id="commerce.order_mapper",
        mapping_version=1,
        mode=MappingMode.ACTIVE,
        shadow_mapping_version=2,
    )

    orm = SqlAlchemyMappingBindingRepository._to_orm_model(binding)
    assert orm.id == binding.id
    assert orm.tenant_id == "ten_01"
    assert orm.connection_id == "conn_01"
    assert orm.stream == "orders"
    assert orm.mapping_id == "commerce.order_mapper"
    assert orm.mapping_version == 1
    assert orm.mode == MappingMode.ACTIVE.value
    assert orm.shadow_mapping_version == 2

    domain = SqlAlchemyMappingBindingRepository._to_domain_model(orm)
    assert domain.id == binding.id
    assert domain.mapping_version == 1
    assert domain.mode == MappingMode.ACTIVE
    assert domain.shadow_mapping_version == 2

    updated = MappingBinding(
        id=binding.id,
        tenant_id=binding.tenant_id,
        connection_id=binding.connection_id,
        stream=binding.stream,
        mapping_id=binding.mapping_id,
        mapping_version=2,
        mode=MappingMode.SHADOW,
        shadow_mapping_version=None,
        created_at=binding.created_at,
        updated_at=datetime.now(UTC),
    )
    SqlAlchemyMappingBindingRepository._update_record_from_domain(orm, updated)
    assert orm.mapping_version == 2
    assert orm.mode == MappingMode.SHADOW.value
    assert orm.shadow_mapping_version is None


def test_normalization_ledger_data_mappers_roundtrip_and_update() -> None:
    entry = NormalizationLedgerEntry.create(
        tenant_id="ten_01",
        replica_record_id="rep_01",
        replica_version=1,
        mapping_id="commerce.order_mapper",
        mapping_version=1,
        produced_canonical_refs=(("commerce.order", "ord_01"), ("commerce.line", "ln_01")),
        outcome=NormalizationOutcome.NORMALIZED,
        trace_id="trc_01",
        correlation_id="corr_01",
    )

    orm = SqlAlchemyNormalizationLedgerRepository._to_orm_model(entry)
    assert orm.id == entry.id
    assert orm.replica_version == 1
    assert orm.outcome == NormalizationOutcome.NORMALIZED.value
    assert orm.produced_canonical_refs == [
        ["commerce.order", "ord_01"],
        ["commerce.line", "ln_01"],
    ]

    domain = SqlAlchemyNormalizationLedgerRepository._to_domain_model(orm)
    assert domain.id == entry.id
    assert domain.replica_version == 1
    assert domain.outcome == NormalizationOutcome.NORMALIZED
    assert domain.produced_canonical_refs == (
        ("commerce.order", "ord_01"),
        ("commerce.line", "ln_01"),
    )

    updated = NormalizationLedgerEntry.create(
        tenant_id="ten_01",
        replica_record_id="rep_01",
        replica_version=2,
        mapping_id="commerce.order_mapper",
        mapping_version=1,
        produced_canonical_refs=(("commerce.order", "ord_01"),),
        outcome=NormalizationOutcome.TOMBSTONED,
        trace_id="trc_02",
        correlation_id="corr_02",
    )
    SqlAlchemyNormalizationLedgerRepository._update_record_from_domain(orm, updated)
    assert orm.replica_version == 2
    assert orm.outcome == NormalizationOutcome.TOMBSTONED.value
    assert orm.produced_canonical_refs == [["commerce.order", "ord_01"]]
    assert orm.trace_id == "trc_02"


def test_normalization_rejection_and_shadow_diff_data_mappers_roundtrip() -> None:
    rejection = NormalizationRejectionEntry.create(
        tenant_id="ten_01",
        replica_record_id="rep_01",
        stream="orders",
        mapping_id="commerce.order_mapper",
        mapping_version=1,
        reason_code=NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED.value,
        field_path="amount",
        detail="Amount must be numeric",
        trace_id="trc_01",
        correlation_id="corr_01",
    )
    orm_rej = SqlAlchemyNormalizationRejectionRepository._to_orm_model(rejection)
    domain_rej = SqlAlchemyNormalizationRejectionRepository._to_domain_model(orm_rej)
    assert domain_rej.id == rejection.id
    assert domain_rej.reason_code == NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED.value
    assert domain_rej.field_path == "amount"
    assert domain_rej.detail == "Amount must be numeric"

    diff = NormalizationShadowDiffEntry.create(
        tenant_id="ten_01",
        replica_record_id="rep_01",
        candidate_version=2,
        diff_data={
            "commerce.order:ord_01": {"fields": {"amount": {"active": 10, "candidate": 12}}}
        },
        trace_id="trc_01",
    )
    orm_diff = SqlAlchemyNormalizationRejectionRepository._shadow_diff_to_orm_model(diff)
    domain_diff = SqlAlchemyNormalizationRejectionRepository._shadow_diff_to_domain_model(orm_diff)
    assert domain_diff.id == diff.id
    assert domain_diff.candidate_version == 2
    assert domain_diff.diff_data == diff.diff_data


def test_pending_reference_data_mappers_roundtrip() -> None:
    entry = PendingReferenceEntry.create(
        tenant_id="ten_01",
        source_connection_id="conn_01",
        target_canonical_type="commerce.customer",
        target_source_id="cust_99",
        referencing_canonical_type="commerce.order",
        referencing_source_id="ord_01",
        referencing_field="customer_id",
        trace_id="trc_01",
    )
    orm = SqlAlchemyPendingReferenceRepository._to_orm_model(entry)
    assert orm.id == entry.id
    assert orm.status == PendingReferenceStatus.PENDING.value

    domain = SqlAlchemyPendingReferenceRepository._to_domain_model(orm)
    assert domain.id == entry.id
    assert domain.target_canonical_type == "commerce.customer"
    assert domain.target_source_id == "cust_99"
    assert domain.referencing_canonical_type == "commerce.order"
    assert domain.referencing_source_id == "ord_01"
    assert domain.referencing_field == "customer_id"
    assert domain.status == PendingReferenceStatus.PENDING
