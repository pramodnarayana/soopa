"""Zero-mock adapter unit tests for Data-Plane ORM-to-Domain Mappers and IP trace stage specs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ip.engine.adapters.outbound.database.data_plane.mappers import (
    entity_map_to_domain,
    inbound_record_to_domain,
    normalization_rejection_to_domain,
    normalized_record_to_domain,
    outbound_record_to_domain,
    replica_record_to_domain,
    replica_rejection_to_domain,
    trace_event_to_domain,
)
from ip.engine.adapters.outbound.database.models.data_plane import (
    GlobalEntityMapModel,
    InboundRecordModel,
    IpTraceEventModel,
    NormalizationRejectionModel,
    NormalizedRecordModel,
    OutboundRecordModel,
    ReplicaRecordModel,
    ReplicaRejectionModel,
)
from ip.engine.application.use_cases.transactions.get_ip_trace_use_case import (
    GetIpTraceUseCase,
)
from ip.engine.domain.constants import REDACTED_SECRET_VALUE
from ip.engine.domain.enums import PipelineLayer
from strace.domain import (
    TraceStageAttemptRow,
    TraceStatus,
    aggregate_trace_lineage_attempts,
)


def test_data_plane_mappers_and_secret_header_redaction() -> None:
    now = datetime.now(UTC)
    inb_orm = InboundRecordModel(
        id="ip_inb_01",
        tenant_id="ten_01",
        connection_id="conn_01",
        app_id="itron_mdm",
        trace_id="ip_trc_01",
        correlation_id="MTR-100",
        parent_trace_id=None,
        original_trace_id="ip_trc_01",
        replay_count=0,
        stream_name="meter_reads",
        ingestion_mode="PUSH_FULL",
        request_headers={"Authorization": "Bearer secret-jwt", "X-Custom": "ok"},
        request_body={"meter_id": "MTR-100"},
        request_s3_key=None,
        request_size_bytes=128,
        request_sha256="abc123",
        received_at=now,
    )
    inb = inbound_record_to_domain(inb_orm)
    assert inb.id == "ip_inb_01"
    assert inb.request_headers["Authorization"] == REDACTED_SECRET_VALUE
    assert inb.request_headers["X-Custom"] == "ok"

    rep_orm = ReplicaRecordModel(
        id="ip_rep_01",
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meter_reads",
        record_key="rk_01",
        primary_key_values=["MTR-100"],
        data={"meter_id": "MTR-100", "kwh": 42.5},
        data_hash="hash_01",
        version=1,
        generation_id=1,
        last_seen_generation=1,
        first_seen_at=now,
        extracted_at=now,
        updated_at=now,
        source_inbound_record_id="ip_inb_01",
        trace_id="ip_trc_01",
        correlation_id="MTR-100",
    )
    rep = replica_record_to_domain(rep_orm)
    assert rep.id == "ip_rep_01"
    assert rep.primary_key_values == ("MTR-100",)

    rep_rej_orm = ReplicaRejectionModel(
        id="ip_rej_01",
        tenant_id="ten_01",
        connection_id="conn_01",
        stream="meter_reads",
        inbound_record_id="ip_inb_01",
        record_index=0,
        reason="MISSING_PRIMARY_KEY",
        detail="Primary key meter_id is null",
        trace_id="ip_trc_01",
        created_at=now,
    )
    rep_rej = replica_rejection_to_domain(rep_rej_orm)
    assert rep_rej.id == "ip_rej_01"

    nrm_orm = NormalizedRecordModel(
        id="ip_nrm_01",
        tenant_id="ten_01",
        connection_id="conn_01",
        canonical_type="mdm.meter_reading",
        source_id="MTR-100",
        canonical_data={"meter_id": "MTR-100", "reading_kwh": 42.5},
        trace_id="ip_trc_01",
        correlation_id="MTR-100",
        parent_trace_id=None,
        original_trace_id="ip_trc_01",
        replay_count=0,
        normalized_at=now,
    )
    nrm = normalized_record_to_domain(nrm_orm)
    assert nrm.id == "ip_nrm_01"
    assert nrm.canonical_type == "mdm.meter_reading"

    nrm_rej_orm = NormalizationRejectionModel(
        id="ip_nrj_01",
        tenant_id="ten_01",
        replica_record_id="ip_rep_01",
        stream="meter_reads",
        mapping_id="itron_meter_v1",
        mapping_version=1,
        reason_code="SCHEMA_VALIDATION_FAILED",
        field_path="reading_kwh",
        detail="Must be non-negative",
        trace_id="ip_trc_01",
        correlation_id="MTR-100",
        created_at=now,
    )
    nrm_rej = normalization_rejection_to_domain(nrm_rej_orm)
    assert nrm_rej.id == "ip_nrj_01"

    gem_orm = GlobalEntityMapModel(
        id="ip_gem_01",
        tenant_id="ten_01",
        trace_id="ip_trc_01",
        correlation_id="MTR-100",
        parent_trace_id=None,
        original_trace_id="ip_trc_01",
        replay_count=0,
        entity_domain="mdm.meter_reading",
        canonical_id="ip_mdmr_01",
        source_connection_id="conn_01",
        source_entity_id="MTR-100",
        dest_connection_id="conn_dest_01",
        dest_entity_id="NS-INV-100",
        created_at=now,
    )
    gem = entity_map_to_domain(gem_orm)
    assert gem.canonical_id == "ip_mdmr_01"

    out_orm = OutboundRecordModel(
        id="ip_out_01",
        tenant_id="ten_01",
        connection_id="conn_dest_01",
        app_id="netsuite_erp",
        trace_id="ip_trc_01",
        correlation_id="MTR-100",
        parent_trace_id=None,
        original_trace_id="ip_trc_01",
        replay_count=0,
        stream_name="invoices",
        operation="CREATE",
        idempotency_key="ip_trc_01:invoices:CREATE",
        external_record_id="NS-INV-100",
        target_url="https://api.netsuite.example.com/v1/invoices",
        http_method="POST",
        request_headers={"X-API-Key": "super-secret-key"},
        request_body={"meter_id": "MTR-100"},
        request_s3_key=None,
        request_size_bytes=64,
        request_sha256="def456",
        response_status_code=201,
        response_headers={"Content-Type": "application/json"},
        response_body={"id": "NS-INV-100"},
        response_s3_key=None,
        duration_ms=145,
        attempt_number=1,
        status="DELIVERED",
        sent_at=now,
    )
    out = outbound_record_to_domain(out_orm)
    assert out.request_headers["X-API-Key"] == REDACTED_SECRET_VALUE

    evt_orm = IpTraceEventModel(
        id="ip_trace_evt_01",
        tenant_id="ten_01",
        trace_id="ip_trc_01",
        correlation_id="MTR-100",
        event_type="L5_DISPATCH_DELIVERED",
        actor="SYSTEM",
        metadata_={"layer": "L5_DELIVER", "status": "SUCCESS"},
        created_at=now,
    )
    evt = trace_event_to_domain(evt_orm)
    assert evt.event_type == "L5_DISPATCH_DELIVERED"

    # Verify derive_overall_status and extract_lineage_context
    status = GetIpTraceUseCase.derive_overall_status(
        outbound_records=(out,),
        normalization_rejections=(),
        normalized_records=(nrm,),
        replica_rejections=(),
        replica_records=(rep,),
        inbound_record=inb,
    )
    assert status == TraceStatus.DELIVERED

    rej_status = GetIpTraceUseCase.derive_overall_status(
        outbound_records=(),
        normalization_rejections=(nrm_rej,),
        normalized_records=(),
        replica_rejections=(rep_rej,),
        replica_records=(),
        inbound_record=None,
    )
    assert rej_status == TraceStatus.REJECTED

    lineage_ctx = GetIpTraceUseCase.extract_lineage_context(
        trace_id="ip_trc_01",
        outbound_records=(out,),
        normalized_records=(nrm,),
        inbound_record=inb,
        replica_records=(rep,),
        trace_events=(evt,),
    )
    assert lineage_ctx.original_trace_id == "ip_trc_01"
    assert lineage_ctx.correlation_id == "MTR-100"


def test_aggregate_lineage_items_merges_and_preserves_replay_order() -> None:
    t0 = datetime.now(UTC)
    t1 = t0 + timedelta(seconds=10)

    root_inb = TraceStageAttemptRow(
        trace_id="ip_trc_root",
        correlation_id="MTR-777",
        status=TraceStatus.INGESTED,
        primary_layer=PipelineLayer.L1_INGEST,
        created_at=t0,
        replay_count=0,
        parent_trace_id=None,
        original_trace_id="ip_trc_root",
    )
    root_out = TraceStageAttemptRow(
        trace_id="ip_trc_root",
        correlation_id="MTR-777",
        status=TraceStatus.FAILED,
        primary_layer=PipelineLayer.L5_DELIVER,
        created_at=t0,
        replay_count=0,
        parent_trace_id=None,
        original_trace_id="ip_trc_root",
    )
    child_out = TraceStageAttemptRow(
        trace_id="ip_trc_child_1",
        correlation_id="MTR-777",
        status=TraceStatus.DELIVERED,
        primary_layer=PipelineLayer.L5_DELIVER,
        created_at=t1,
        replay_count=1,
        parent_trace_id="ip_trc_root",
        original_trace_id="ip_trc_root",
    )

    items = aggregate_trace_lineage_attempts(
        stage_batches_in_pipeline_order=((root_inb,), (), (root_out, child_out)),
        fallback_root_trace_id="ip_trc_root",
    )
    assert len(items) == 2
    assert items[0].trace_id == "ip_trc_root"
    assert items[0].status == TraceStatus.FAILED
    assert items[0].primary_layer == PipelineLayer.L5_DELIVER.value
    assert items[1].trace_id == "ip_trc_child_1"
    assert items[1].status == TraceStatus.DELIVERED
    assert items[1].replay_count == 1
