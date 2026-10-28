"""Pure zero-mock unit tests for IP Transactions HTTP DTO mappers."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from strace.domain import TraceStatus

from ip.engine.adapters.inbound.api.dtos.transaction_dtos import (
    map_bulk_replay_result_to_http,
    map_ip_trace_dto_to_http,
    map_lineage_item_to_http,
    map_replay_result_to_http,
)
from ip.engine.application.dtos.trace import (
    BulkReplayFailureItemDTO,
    BulkReplayResultDTO,
    IpTraceDTO,
    IpTraceLineageItemDTO,
    ReplayTransactionResultDTO,
)
from ip.engine.domain.enums import (
    OutboundDispatchStatus,
    PipelineLayer,
    ReplayStage,
    TimelineStatus,
)
from ip.engine.domain.exceptions import IpErrorCode
from ip.engine.domain.models.global_entity_map import GlobalEntityMap
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.normalized_record import NormalizedRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.domain.models.replica_record import ReplicaRecord, ReplicaRejection
from ip.engine.domain.models.timeline_entry import IpTraceEvent
from ip.engine.domain.normalization import NormalizationRejectionEntry


def test_map_ip_trace_dto_to_http_maps_all_five_layers_and_decimals() -> None:
    tenant_id = "ten_01"
    trace_id = "ip_trc_unit_01"

    inb = InboundRecord.create(
        tenant_id=tenant_id,
        connection_id="conn_01",
        app_id="itron_mdm",
        stream_name="meters",
        payload_bytes=b'{"meter_id":"MTR-100"}',
        is_inlined=True,
        trace_id=trace_id,
        correlation_id="MTR-100",
        request_body={"meter_id": "MTR-100"},
    )
    rep = ReplicaRecord.create(
        tenant_id=tenant_id,
        connection_id="conn_01",
        stream="meters",
        primary_key_values=("MTR-100",),
        data={"meter_id": "MTR-100", "kwh": 42.5},
        source_inbound_record_id=inb.id,
        trace_id=trace_id,
        correlation_id="MTR-100",
    )
    rep_rej = ReplicaRejection.create(
        tenant_id=tenant_id,
        connection_id="conn_01",
        stream="meters",
        inbound_record_id=inb.id,
        record_index=1,
        reason="MISSING_PK",
        detail="Missing meter_id",
        trace_id=trace_id,
    )
    norm = NormalizedRecord.create(
        tenant_id=tenant_id,
        connection_id="conn_01",
        canonical_type="energy.meter_reading",
        source_id="MTR-100",
        canonical_data={
            "meter_id": "MTR-100",
            "reading_kwh": Decimal("128.7500"),
            "nested": {"tariff": "0.15"},
            "readings_list": ["10.5", "20.25"],
        },
        trace_id=trace_id,
        correlation_id="MTR-100",
    )
    norm_rej = NormalizationRejectionEntry.create(
        tenant_id=tenant_id,
        replica_record_id=rep.id,
        stream="meters",
        transformation_id="itron.meters",
        transformation_version=1,
        reason_code="QUALITY_RULE_FAILED",
        field_path="reading_kwh",
        detail="Negative reading",
        trace_id=trace_id,
        correlation_id="MTR-100",
    )
    gem = GlobalEntityMap.create(
        tenant_id=tenant_id,
        trace_id=trace_id,
        entity_domain="energy.meter",
        canonical_id="can_mtr_100",
        source_connection_id="conn_01",
        source_entity_id="MTR-100",
        dest_connection_id="conn_sap",
        dest_entity_id="SAP-900",
        correlation_id="MTR-100",
    )
    out = OutboundRecord.create_pending(
        tenant_id=tenant_id,
        connection_id="conn_sap",
        app_id="sap_isu",
        stream_name="meter_readings",
        target_url="https://sap.example.com/readings",
        http_method="POST",
        payload_bytes=b'{"sap_id":"SAP-900"}',
        is_inlined=True,
        trace_id=trace_id,
        correlation_id="MTR-100",
        request_body={"sap_id": "SAP-900"},
        status=OutboundDispatchStatus.DELIVERED,
    )
    event = IpTraceEvent.create(
        tenant_id=tenant_id,
        trace_id=trace_id,
        correlation_id="MTR-100",
        event_type="L5_DELIVERED",
        actor="SYSTEM",
        layer=PipelineLayer.L5_DELIVER,
        status=TimelineStatus.SUCCESS,
        summary_message="Delivered to SAP IS-U.",
    )

    trace_dto = IpTraceDTO(
        trace_id=trace_id,
        tenant_id=tenant_id,
        correlation_id="MTR-100",
        original_trace_id=trace_id,
        parent_trace_id=None,
        replay_count=0,
        status=TraceStatus.DELIVERED,
        inbound_record=inb,
        replica_records=(rep,),
        replica_rejections=(rep_rej,),
        normalized_records=(norm,),
        normalization_rejections=(norm_rej,),
        entity_mappings=(gem,),
        outbound_records=(out,),
        trace_events=(event,),
    )

    http_resp = map_ip_trace_dto_to_http(trace_dto)
    assert http_resp.trace_id == trace_id
    assert http_resp.status == "DELIVERED"
    assert http_resp.inbound_record is not None
    assert http_resp.inbound_record.id == inb.id
    assert len(http_resp.replica_records) == 1
    assert len(http_resp.replica_rejections) == 1
    assert len(http_resp.normalized_records) == 1
    assert http_resp.normalized_records[0].canonical_data["reading_kwh"] == "128.7500"
    assert http_resp.normalized_records[0].canonical_data["nested"] == {"tariff": "0.15"}
    assert http_resp.normalized_records[0].canonical_data["readings_list"] == ["10.5", "20.25"]
    assert len(http_resp.normalization_rejections) == 1
    assert len(http_resp.entity_mappings) == 1
    assert http_resp.entity_mappings[0].dest_entity_id == "SAP-900"
    assert len(http_resp.outbound_records) == 1
    assert http_resp.outbound_records[0].status == "DELIVERED"
    assert len(http_resp.trace_events) == 1


def test_map_lineage_and_replay_results_to_http() -> None:
    now = datetime.now(UTC)
    lineage_item = IpTraceLineageItemDTO(
        trace_id="ip_trc_child",
        correlation_id="MTR-100",
        status=TraceStatus.INGESTED,
        primary_layer="L1_INGRESS",
        created_at=now,
        replay_count=1,
        parent_trace_id="ip_trc_root",
        original_trace_id="ip_trc_root",
    )
    http_lineage = map_lineage_item_to_http(lineage_item)
    assert http_lineage.trace_id == "ip_trc_child"
    assert http_lineage.status == "INGESTED"
    assert http_lineage.created_at == now.isoformat()

    replay_res = ReplayTransactionResultDTO(
        original_trace_id="ip_trc_root",
        parent_trace_id="ip_trc_root",
        new_trace_id="ip_trc_child",
        stage=ReplayStage.RETRY_INGEST,
        replay_count=1,
        correlation_id="MTR-100",
    )
    http_replay = map_replay_result_to_http(replay_res)
    assert http_replay.status == "ACCEPTED"
    assert http_replay.new_trace_id == "ip_trc_child"
    assert http_replay.stage == "RETRY_INGEST"

    bulk_res = BulkReplayResultDTO(
        stage=ReplayStage.RETRY_INGEST,
        replayed_count=1,
        succeeded_trace_ids=("ip_trc_root",),
        new_trace_ids=("ip_trc_child",),
        failed_items=(
            BulkReplayFailureItemDTO(
                trace_id="ip_trc_missing",
                error_code=IpErrorCode.TRACE_NOT_FOUND,
                message="Trace not found",
            ),
        ),
    )
    http_bulk = map_bulk_replay_result_to_http(bulk_res)
    assert http_bulk.replayed_count == 1
    assert http_bulk.succeeded_trace_ids == ["ip_trc_root"]
    assert len(http_bulk.failed_items) == 1
    assert http_bulk.failed_items[0].error_code == "TRACE_NOT_FOUND"
