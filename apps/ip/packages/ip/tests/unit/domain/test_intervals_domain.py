"""Unit tests for High-Frequency Interval Streams domain aggregates and invariants."""

from __future__ import annotations

from datetime import UTC, datetime

from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.intervals.enums import (
    BatchManifestStatus,
    IntervalPayloadFormat,
    PriorityLane,
)
from ip.engine.domain.intervals.events import (
    FeederOutageClusterDetectedEvent,
    IntervalBatchIngestedEvent,
    IntervalBatchProcessedEvent,
)
from ip.engine.domain.intervals.models import (
    BatchManifest,
    BatchReconciliationCounts,
    FeederOutageCluster,
)
from ip.engine.domain.trace.enums import IpTraceEventType
from seedwork.events import EventProcessingLane


def test_batch_reconciliation_counts_zero_loss_equation_balanced() -> None:
    balanced = BatchReconciliationCounts(
        raw_ingested=5000,
        duplicates_dropped=120,
        valid_canonical=4850,
        quarantined_held=30,
    )
    assert balanced.is_balanced() is True
    assert balanced.accounted_total == 5000

    imbalanced = BatchReconciliationCounts(
        raw_ingested=5000,
        duplicates_dropped=100,
        valid_canonical=4850,
        quarantined_held=30,
    )
    assert imbalanced.is_balanced() is False
    assert imbalanced.accounted_total == 4980


def test_batch_manifest_create_ingested_emits_domain_events() -> None:
    window_start = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    window_end = datetime(2026, 11, 9, 10, 15, tzinfo=UTC)
    manifest = BatchManifest.create_ingested(
        tenant_id="tenant_utility_01",
        app_id="app_interval_source",
        connection_id="conn_interval_01",
        stream_name="interval_readings_15m",
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
        priority_lane=PriorityLane.P2_BULK_REPLAY,
        l1_raw_uri="s3://ip-tiered-storage/l1_raw/batch_01.json",
        payload_sha256="a" * 64,
        payload_size_bytes=4096,
        raw_ingested_count=5000,
        window_start_utc=window_start,
        window_end_utc=window_end,
        trace_id="trc_interval_001",
        correlation_id="corr_interval_001",
    )

    assert manifest.id.startswith(f"{IpIdPrefix.INTERVAL_BATCH.value}_")
    assert manifest.status is BatchManifestStatus.INGESTED
    assert manifest.reconciliation_counts.raw_ingested == 5000
    assert manifest.trace_id == "trc_interval_001"

    events = manifest.domain_events
    assert len(events) == 1
    ingested_evt = events[0]
    assert isinstance(ingested_evt, IntervalBatchIngestedEvent)
    assert ingested_evt.batch_id == manifest.id
    assert ingested_evt.raw_ingested_count == 5000

    traces = manifest.trace_events
    assert len(traces) == 1
    assert traces[0].event_type == IpTraceEventType.INTERVAL_BATCH_INGESTED.value


def test_batch_manifest_promote_outage_clusters_emits_critical_events() -> None:
    window_start = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    window_end = datetime(2026, 11, 9, 10, 15, tzinfo=UTC)
    manifest = BatchManifest.create_ingested(
        tenant_id="tenant_utility_01",
        app_id="app_interval_source",
        connection_id="conn_interval_01",
        stream_name="interval_readings_15m",
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
        priority_lane=PriorityLane.P2_BULK_REPLAY,
        l1_raw_uri="s3://ip-tiered-storage/l1_raw/batch_01.json",
        payload_sha256="b" * 64,
        payload_size_bytes=2048,
        raw_ingested_count=100,
        window_start_utc=window_start,
        window_end_utc=window_end,
    )
    manifest.clear_domain_events()
    manifest.clear_trace_events()

    cluster = FeederOutageCluster(
        cluster_id=f"{IpIdPrefix.OUTAGE_CLUSTER.value}_01",
        tenant_id="tenant_utility_01",
        connection_id="conn_interval_01",
        batch_id=manifest.id,
        feeder_id="FDR_NORTH_12",
        substation_id="SUB_99",
        outage_meter_count=42,
        affected_meter_ids=("DEV_01", "DEV_02"),
        outage_start_utc=window_end,
        trace_id=manifest.trace_id,
    )
    manifest.promote_outage_clusters((cluster,))

    assert manifest.promoted_outage_clusters_count == 1

    events = manifest.domain_events
    assert len(events) == 1
    outage_evt = events[0]
    assert isinstance(outage_evt, FeederOutageClusterDetectedEvent)
    assert outage_evt.feeder_id == "FDR_NORTH_12"
    assert outage_evt.outage_meter_count == 42

    traces = manifest.trace_events
    assert len(traces) == 1
    assert traces[0].event_type == IpTraceEventType.FEEDER_OUTAGE_PROMOTED.value


def test_batch_manifest_complete_reconciled_enforces_zero_loss_invariant() -> None:
    window_start = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    window_end = datetime(2026, 11, 9, 10, 15, tzinfo=UTC)
    manifest = BatchManifest.create_ingested(
        tenant_id="tenant_utility_01",
        app_id="app_interval_source",
        connection_id="conn_interval_01",
        stream_name="interval_readings_15m",
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
        priority_lane=PriorityLane.P2_BULK_REPLAY,
        l1_raw_uri="s3://ip-tiered-storage/l1_raw/batch_01.json",
        payload_sha256="c" * 64,
        payload_size_bytes=2048,
        raw_ingested_count=100,
        window_start_utc=window_start,
        window_end_utc=window_end,
    )
    manifest.clear_domain_events()
    manifest.clear_trace_events()

    imbalanced_counts = BatchReconciliationCounts(
        raw_ingested=100,
        duplicates_dropped=5,
        valid_canonical=90,
        quarantined_held=2,
    )
    fail_res = manifest.complete_reconciled(
        counts=imbalanced_counts,
        l2_replica_uri="s3://ip-tiered-storage/l2/replica.arrow",
        l3_canonical_uri="s3://ip-tiered-storage/l3/valid.arrow",
    )
    assert fail_res.is_err is True
    assert manifest.status.value == BatchManifestStatus.INGESTED.value

    balanced_counts = BatchReconciliationCounts(
        raw_ingested=100,
        duplicates_dropped=5,
        valid_canonical=93,
        quarantined_held=2,
    )
    ok_res = manifest.complete_reconciled(
        counts=balanced_counts,
        l2_replica_uri="s3://ip-tiered-storage/l2/replica.arrow",
        l3_canonical_uri="s3://ip-tiered-storage/l3/valid.arrow",
    )
    assert ok_res.is_ok is True
    assert manifest.status.value == BatchManifestStatus.COMPLETED.value
    assert manifest.l2_replica_uri == "s3://ip-tiered-storage/l2/replica.arrow"
    assert manifest.l3_canonical_uri == "s3://ip-tiered-storage/l3/valid.arrow"

    events = manifest.domain_events
    assert len(events) == 1
    assert isinstance(events[0], IntervalBatchProcessedEvent)


def test_batch_manifest_record_delivery_receipt_records_settlement_reference() -> None:
    window_start = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    window_end = datetime(2026, 11, 9, 10, 15, tzinfo=UTC)
    manifest = BatchManifest.create_ingested(
        tenant_id="tenant_utility_01",
        app_id="app_interval_source",
        connection_id="conn_interval_01",
        stream_name="interval_readings_15m",
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
        priority_lane=PriorityLane.P2_BULK_REPLAY,
        l1_raw_uri="s3://ip-tiered-storage/l1_raw/batch_01.json",
        payload_sha256="d" * 64,
        payload_size_bytes=1024,
        raw_ingested_count=10,
        window_start_utc=window_start,
        window_end_utc=window_end,
    )
    manifest.complete_reconciled(
        counts=BatchReconciliationCounts(
            raw_ingested=10,
            duplicates_dropped=0,
            valid_canonical=10,
            quarantined_held=0,
        ),
        l2_replica_uri="s3://ip-tiered-storage/l2/replica.arrow",
        l3_canonical_uri="s3://ip-tiered-storage/l3/valid.arrow",
    )
    manifest.clear_trace_events()

    manifest.record_delivery_receipt(delivery_receipt_id="SETTLEMENT-DOC-998877")
    assert manifest.delivery_receipt_id == "SETTLEMENT-DOC-998877"

    traces = manifest.trace_events
    assert len(traces) == 1
    assert traces[0].event_type == IpTraceEventType.SETTLEMENT_RECEIPT_RECORDED.value


def test_batch_manifest_mark_failed_records_error_message() -> None:
    window_start = datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    window_end = datetime(2026, 11, 9, 10, 15, tzinfo=UTC)
    manifest = BatchManifest.create_ingested(
        tenant_id="tenant_utility_01",
        app_id="app_interval_source",
        connection_id="conn_interval_01",
        stream_name="interval_readings_15m",
        payload_format=IntervalPayloadFormat.JSON_ARRAY,
        priority_lane=PriorityLane.P2_BULK_REPLAY,
        l1_raw_uri="s3://ip-tiered-storage/l1_raw/batch_01.json",
        payload_sha256="e" * 64,
        payload_size_bytes=512,
        raw_ingested_count=10,
        window_start_utc=window_start,
        window_end_utc=window_end,
    )
    manifest.mark_failed("Corrupted Arrow IPC footer")
    assert manifest.status is BatchManifestStatus.FAILED
    assert manifest.error_message == "Corrupted Arrow IPC footer"


def test_batch_manifest_mark_processing_transitions_state() -> None:
    manifest = BatchManifest.create_ingested(
        tenant_id="tenant_utility_01",
        app_id="app_interval_source",
        connection_id="conn_interval_01",
        stream_name="interval_readings_15m",
        l1_raw_uri="s3://ip/l1.json",
        payload_sha256="f" * 64,
        payload_size_bytes=100,
        raw_ingested_count=10,
        window_start_utc=datetime.now(UTC),
        window_end_utc=datetime.now(UTC),
    )
    manifest.mark_processing()
    assert manifest.status is BatchManifestStatus.PROCESSING

    # Empty promote early returns without muting counts
    manifest.promote_outage_clusters(())
    assert manifest.promoted_outage_clusters_count == 0

    res = manifest.complete_reconciled(
        counts=BatchReconciliationCounts(raw_ingested=10, valid_canonical=10),
        delivery_receipt_id="RCPT-DIRECT",
    )
    assert res.is_ok is True
    assert manifest.delivery_receipt_id == "RCPT-DIRECT"


def test_interval_domain_events_contract_lanes() -> None:
    ingested_p0 = IntervalBatchIngestedEvent(
        batch_id="bch_01",
        tenant_id="ten_01",
        trace_id="trc_01",
        correlation_id="corr_01",
        priority_lane=PriorityLane.P0_CRITICAL.value,
    )
    assert ingested_p0.event_name == "ip.interval_batch.ingested"
    assert ingested_p0.get_routing_tenant_id() == "ten_01"
    assert ingested_p0.get_trace_id() == "trc_01"
    assert ingested_p0.get_correlation_id() == "corr_01"
    assert ingested_p0.get_processing_lane() == EventProcessingLane.REALTIME

    ingested_p1 = IntervalBatchIngestedEvent(
        priority_lane=PriorityLane.P1_LIVE.value,
    )
    assert ingested_p1.get_processing_lane() == EventProcessingLane.BULK
    assert ingested_p1.get_trace_id() is None

    processed = IntervalBatchProcessedEvent(
        batch_id="bch_02",
        tenant_id="ten_02",
        trace_id="trc_02",
        correlation_id="corr_02",
    )
    assert processed.event_name == "ip.interval_batch.processed"
    assert processed.get_routing_tenant_id() == "ten_02"
    assert processed.get_trace_id() == "trc_02"
    assert processed.get_correlation_id() == "corr_02"
    assert processed.get_processing_lane() == EventProcessingLane.BULK

    outage = FeederOutageClusterDetectedEvent(
        cluster_id="cls_01",
        tenant_id="ten_03",
        trace_id="trc_03",
        correlation_id="corr_03",
    )
    assert outage.event_name == "ip.feeder_outage.detected"
    assert outage.get_routing_tenant_id() == "ten_03"
    assert outage.get_trace_id() == "trc_03"
    assert outage.get_correlation_id() == "corr_03"
    assert outage.get_processing_lane() == EventProcessingLane.REALTIME
