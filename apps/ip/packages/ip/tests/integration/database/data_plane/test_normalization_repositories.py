"""Narrow Integration Tests for Layer 3 Data Plane repositories against real PostgreSQL."""

from __future__ import annotations

import pytest
from database.types import TenantSession
from ip.engine.adapters.outbound.database.data_plane.normalization_ledger_repository import (
    SqlAlchemyNormalizationLedgerRepository,
)
from ip.engine.adapters.outbound.database.data_plane.normalization_rejection_repository import (
    SqlAlchemyNormalizationRejectionRepository,
)
from ip.engine.adapters.outbound.database.data_plane.pending_reference_repository import (
    SqlAlchemyPendingReferenceRepository,
)
from ip.engine.adapters.outbound.database.data_plane.replica_record_repository import (
    SqlAlchemyReplicaRecordRepository,
)
from ip.engine.domain.enums import (
    NormalizationOutcome,
    NormalizationRejectionReason,
    PendingReferenceStatus,
)
from ip.engine.domain.models.replica_record import ReplicaRecord
from ip.engine.domain.normalization import (
    NormalizationLedgerEntry,
    NormalizationRejectionEntry,
    NormalizationShadowDiffEntry,
    PendingReferenceEntry,
)

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_normalization_ledger_repository_operations(
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    repo = SqlAlchemyNormalizationLedgerRepository(tenant_session)

    # 1. Initially no version recorded
    v0 = await repo.get_latest_version(
        tenant_id=seeded_ip_tenant,
        replica_record_id="rep_test_1",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    assert v0 is None

    # 2. Record entry
    entry = NormalizationLedgerEntry.create(
        tenant_id=seeded_ip_tenant,
        replica_record_id="rep_test_1",
        replica_version=1,
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
        produced_canonical_refs=(
            ("energy.meter_reading", "mr_1"),
            ("energy.meter_reading", "mr_2"),
        ),
        outcome=NormalizationOutcome.NORMALIZED,
        trace_id="trc_ledg_1",
        correlation_id="corr_1",
    )
    await repo.record_entry(entry)

    # 3. Query latest version
    v1 = await repo.get_latest_version(
        tenant_id=seeded_ip_tenant,
        replica_record_id="rep_test_1",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    assert v1 == 1

    # 4. Query produced refs
    refs = await repo.get_produced_refs(
        tenant_id=seeded_ip_tenant,
        replica_record_id="rep_test_1",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    assert len(refs) == 2
    assert ("energy.meter_reading", "mr_1") in refs
    assert ("energy.meter_reading", "mr_2") in refs

    # 5. Upsert newer version
    entry_v2 = NormalizationLedgerEntry.create(
        tenant_id=seeded_ip_tenant,
        replica_record_id="rep_test_1",
        replica_version=2,
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
        produced_canonical_refs=(("energy.meter_reading", "mr_1"),),
        outcome=NormalizationOutcome.NORMALIZED,
        trace_id="trc_ledg_2",
    )
    await repo.record_entry(entry_v2)

    v2 = await repo.get_latest_version(
        tenant_id=seeded_ip_tenant,
        replica_record_id="rep_test_1",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    assert v2 == 2

    refs_v2 = await repo.get_produced_refs(
        tenant_id=seeded_ip_tenant,
        replica_record_id="rep_test_1",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
    )
    assert len(refs_v2) == 1
    assert refs_v2[0] == ("energy.meter_reading", "mr_1")


@pytest.mark.asyncio
async def test_normalization_rejection_and_shadow_diff_repository(
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    repo = SqlAlchemyNormalizationRejectionRepository(tenant_session)

    # Record rejection
    rej = NormalizationRejectionEntry.create(
        tenant_id=seeded_ip_tenant,
        replica_record_id="rep_rej_1",
        stream="readings",
        mapping_id="energy.ami_meter_reading",
        mapping_version=1,
        reason_code=NormalizationRejectionReason.SCHEMA_VALIDATION_FAILED.value,
        field_path="kwh",
        detail="Value cannot be negative",
        trace_id="trc_rej_1",
    )
    await repo.record_rejection(rej)

    # Record shadow diff
    diff = NormalizationShadowDiffEntry.create(
        tenant_id=seeded_ip_tenant,
        replica_record_id="rep_rej_1",
        candidate_version=2,
        diff_data={"kwh": {"active": 10.0, "candidate": 10.5}},
        trace_id="trc_diff_1",
    )
    await repo.record_shadow_diff(diff)


@pytest.mark.asyncio
async def test_pending_reference_repository_operations(
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    repo = SqlAlchemyPendingReferenceRepository(tenant_session)

    pref1 = PendingReferenceEntry.create(
        tenant_id=seeded_ip_tenant,
        source_connection_id="conn_ami_1",
        target_canonical_type="energy.service_point",
        target_source_id="sp_target_100",
        referencing_canonical_type="energy.meter_reading",
        referencing_source_id="mr_ref_1",
        referencing_field="service_point_id",
        trace_id="trc_pref_1",
    )
    await repo.record_pending(pref1)

    pref2 = PendingReferenceEntry.create(
        tenant_id=seeded_ip_tenant,
        source_connection_id="conn_ami_1",
        target_canonical_type="energy.service_point",
        target_source_id="sp_target_100",
        referencing_canonical_type="energy.meter_reading",
        referencing_source_id="mr_ref_2",
        referencing_field="service_point_id",
        trace_id="trc_pref_2",
    )
    await repo.record_pending(pref2)

    # Unrelated pending reference
    pref_other = PendingReferenceEntry.create(
        tenant_id=seeded_ip_tenant,
        source_connection_id="conn_ami_1",
        target_canonical_type="energy.service_point",
        target_source_id="sp_other_999",
        referencing_canonical_type="energy.meter_reading",
        referencing_source_id="mr_ref_3",
        referencing_field="service_point_id",
        trace_id="trc_pref_3",
    )
    await repo.record_pending(pref_other)

    # Resolve pending for target "sp_target_100"
    resolved = await repo.resolve_pending_for_target(
        tenant_id=seeded_ip_tenant,
        source_connection_id="conn_ami_1",
        target_canonical_type="energy.service_point",
        target_source_id="sp_target_100",
    )
    assert len(resolved) == 2
    resolved_ids = {r.id for r in resolved}
    assert pref1.id in resolved_ids
    assert pref2.id in resolved_ids
    for r in resolved:
        assert r.status == PendingReferenceStatus.RESOLVED
        assert r.resolved_at is not None

    # Resolving again returns empty list because status is already RESOLVED
    re_resolved = await repo.resolve_pending_for_target(
        tenant_id=seeded_ip_tenant,
        source_connection_id="conn_ami_1",
        target_canonical_type="energy.service_point",
        target_source_id="sp_target_100",
    )
    assert len(re_resolved) == 0


@pytest.mark.asyncio
async def test_replica_record_repository_list_by_stream_chunk(
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    repo = SqlAlchemyReplicaRecordRepository(tenant_session)

    for idx in range(5):
        rec = ReplicaRecord.create(
            tenant_id=seeded_ip_tenant,
            connection_id="conn_chunk_1",
            stream="readings_chunk",
            record_key=f"rk_chunk_{idx}",
            data={"kwh": float(idx)},
            trace_id=f"trc_chunk_{idx}",
        )
        await repo.save(rec)

    chunk_1 = await repo.list_by_stream_chunk(
        tenant_id=seeded_ip_tenant,
        connection_id="conn_chunk_1",
        stream="readings_chunk",
        after_id=None,
        limit=2,
    )
    assert len(chunk_1) == 2

    chunk_2 = await repo.list_by_stream_chunk(
        tenant_id=seeded_ip_tenant,
        connection_id="conn_chunk_1",
        stream="readings_chunk",
        after_id=chunk_1[-1].id,
        limit=2,
    )
    assert len(chunk_2) == 2

    chunk_3 = await repo.list_by_stream_chunk(
        tenant_id=seeded_ip_tenant,
        connection_id="conn_chunk_1",
        stream="readings_chunk",
        after_id=chunk_2[-1].id,
        limit=2,
    )
    assert len(chunk_3) == 1

    chunk_4 = await repo.list_by_stream_chunk(
        tenant_id=seeded_ip_tenant,
        connection_id="conn_chunk_1",
        stream="readings_chunk",
        after_id=chunk_3[-1].id,
        limit=2,
    )
    assert len(chunk_4) == 0
