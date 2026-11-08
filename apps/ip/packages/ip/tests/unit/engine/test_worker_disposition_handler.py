"""Unit tests for IP Engine worker payload DTO parsing and result disposition handling."""

from __future__ import annotations

from ip.engine.adapters.inbound.workers import (
    IpCanonicalRecordChunkPayloadDTO,
    IpFetchRecordChunkPayloadDTO,
    IpGenerationCompletedPayloadDTO,
    IpInboundRecordChunkPayloadDTO,
    IpNormalizedRecordChunkPayloadDTO,
    IpOutboundRecordChunkPayloadDTO,
    IpReplicaRecordChunkPayloadDTO,
    IpStreamBackfillPayloadDTO,
    IpSyncRunRequestedPayloadDTO,
    IpWorkerResultDispositionHandler,
)
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.enums import IpEventType
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.domain.replication.enums import SyncRunKind
from pubsub.enums import ConsumerAction
from seedwork.events import EventEnvelope


def test_inbound_chunk_payload_dto_parses_chunk_pointers_with_single_id_fallback() -> None:
    inbound_env = EventEnvelope(
        id="evt_1",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k_1",
        trace_id="tr_1",
        payload={
            "connection_id": "conn_1",
            "stream_name": "records_alpha",
            "record_ids": ["inb_1", "inb_2"],
            "generation_id": 2,
        },
    )
    inbound_res = IpInboundRecordChunkPayloadDTO.from_envelope(inbound_env)
    assert inbound_res.is_ok
    assert inbound_res.unwrap().record_ids == ("inb_1", "inb_2")
    assert inbound_res.unwrap().generation_id == 2

    inbound_single = IpInboundRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_2",
            source="ip.data_plane",
            event_type=IpEventType.INBOUND_RECORD_CREATED.value,
            tenant_id="t_01",
            idempotency_key="k_2",
            payload={
                "connection_id": "conn_1",
                "stream": "records_alpha",
                "record_id": "inb_single",
            },
        )
    )
    assert inbound_single.is_ok
    assert inbound_single.unwrap().record_ids == ("inb_single",)

    inbound_invalid = IpInboundRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_bad",
            source="ip.data_plane",
            event_type=IpEventType.INBOUND_RECORD_CREATED.value,
            tenant_id="t_01",
            idempotency_key="k_bad",
            payload={"connection_id": "conn_1", "stream_name": "records_alpha"},
        )
    )
    assert inbound_invalid.is_err
    assert inbound_invalid.unwrap_err().code == IpErrorCode.VALIDATION_FAILED


def test_inbound_chunk_payload_dto_parses_range_claim_check_without_record_ids() -> None:
    range_env = EventEnvelope(
        id="evt_range_1",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k_range_1",
        trace_id="tr_range_1",
        payload={
            "connection_id": "conn_1",
            "stream_name": "orders",
            "batch_id": "ip_bch_abc123",
            "range_start": "ip_inb_abc123_00000000",
            "range_end": "ip_inb_abc123_00000499",
            "count": 500,
            "causation_depth": 1,
        },
    )
    parsed_res = IpInboundRecordChunkPayloadDTO.from_envelope(range_env)
    assert parsed_res.is_ok
    dto = parsed_res.unwrap()
    assert dto.batch_id == "ip_bch_abc123"
    assert dto.range_start == "ip_inb_abc123_00000000"
    assert dto.range_end == "ip_inb_abc123_00000499"
    assert dto.count == 500
    assert dto.causation_depth == 1
    assert dto.record_ids == ()


def test_pipeline_stage_payload_dtos_parse_valid_envelopes() -> None:
    replica_res = IpReplicaRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_rep",
            source="ip.data_plane",
            event_type=IpEventType.REPLICA_RECORD_CHANGED.value,
            tenant_id="t_01",
            idempotency_key="k_rep",
            payload={
                "connection_id": "conn_1",
                "stream": "records_alpha",
                "record_ids": ["rep_1", "rep_2", "rep_3"],
                "version": 4,
            },
        )
    )
    assert replica_res.is_ok
    assert replica_res.unwrap().record_ids == ("rep_1", "rep_2", "rep_3")
    assert replica_res.unwrap().version == 4

    norm_res = IpNormalizedRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_norm",
            source="ip.data_plane",
            event_type=IpEventType.NORMALIZED_RECORD_CREATED.value,
            tenant_id="t_01",
            idempotency_key="k_norm",
            payload={
                "connection_id": "conn_1",
                "canonical_type": "canonical.record_alpha.v1",
                "source_id": "REC-1",
                "record_id": "norm_1",
            },
        )
    )
    assert norm_res.is_ok
    assert norm_res.unwrap().record_ids == ("norm_1",)

    canon_res = IpCanonicalRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_canon",
            source="ip.data_plane",
            event_type=IpEventType.CANONICAL_RECORD_CHANGED.value,
            tenant_id="t_01",
            idempotency_key="k_canon",
            payload={
                "connection_id": "conn_1",
                "canonical_type": "canonical.record_alpha.v1",
                "source_id": "REC-100",
            },
        )
    )
    assert canon_res.is_ok
    assert canon_res.unwrap().record_ids == ("REC-100",)

    outbound_res = IpOutboundRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_out",
            source="ip.data_plane",
            event_type=IpEventType.OUTBOUND_RECORD_CREATED.value,
            tenant_id="t_01",
            idempotency_key="k_out",
            payload={
                "connection_id": "conn_1",
                "stream_name": "erp_invoices",
                "record_ids": ["out_1", "out_2"],
            },
        )
    )
    assert outbound_res.is_ok
    assert outbound_res.unwrap().record_ids == ("out_1", "out_2")

    fetch_res = IpFetchRecordChunkPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_fetch",
            source="ip.data_plane",
            event_type=IpEventType.FETCH_RECORD_REQUESTED.value,
            tenant_id="t_01",
            idempotency_key="k_fetch",
            payload={
                "connection_id": "conn_1",
                "stream": "orders",
                "record_id": "ORD-1",
                "notice_inbound_record_id": "inb_notice_1",
            },
        )
    )
    assert fetch_res.is_ok
    assert fetch_res.unwrap().record_ids == ("ORD-1",)

    gen_res = IpGenerationCompletedPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_gen",
            source="ip.data_plane",
            event_type=IpEventType.GENERATION_COMPLETED.value,
            tenant_id="t_01",
            idempotency_key="k_gen",
            payload={"connection_id": "conn_1", "stream": "records_alpha", "generation_id": 7},
        )
    )
    assert gen_res.is_ok
    assert gen_res.unwrap().generation_id == 7

    backfill_res = IpStreamBackfillPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_bf",
            source="ip.control_plane",
            event_type=IpEventType.TRANSFORMATION_VERSION_PROMOTED.value,
            tenant_id="t_01",
            idempotency_key="k_bf",
            payload={
                "connection_id": "conn_1",
                "stream": "records_alpha",
                "transformation_id": "map_1",
            },
        )
    )
    assert backfill_res.is_ok
    assert backfill_res.unwrap().transformation_id == "map_1"

    sync_res = IpSyncRunRequestedPayloadDTO.from_envelope(
        EventEnvelope(
            id="evt_sync",
            source="ip.control_plane",
            event_type=IpEventType.SYNC_RUN_REQUESTED.value,
            tenant_id="t_01",
            idempotency_key="k_sync",
            payload={
                "connection_id": "conn_1",
                "stream": "records_alpha",
                "kind": SyncRunKind.INCREMENTAL.value,
            },
        )
    )
    assert sync_res.is_ok
    assert sync_res.unwrap().forced_kind is SyncRunKind.INCREMENTAL


def test_disposition_handler_maps_single_result_failure_dispositions() -> None:
    env = EventEnvelope(
        id="evt_disp",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k_disp",
        payload={},
    )

    assert (
        IpWorkerResultDispositionHandler.to_consumer_action(env, Result.ok("ok"))
        == ConsumerAction.ACK
    )

    retry_err = IpError(
        code=IpErrorCode.EXTERNAL_API_ERROR,
        message="Rate limited",
        disposition=FailureDisposition.RETRY,
    )
    assert (
        IpWorkerResultDispositionHandler.to_consumer_action(env, Result.err(retry_err))
        == ConsumerAction.NACK
    )

    fail_err = IpError(
        code=IpErrorCode.VALIDATION_FAILED,
        message="Poison pill",
        disposition=FailureDisposition.FAIL,
    )
    assert (
        IpWorkerResultDispositionHandler.to_consumer_action(env, Result.err(fail_err))
        == ConsumerAction.DLQ
    )

    ignore_err = IpError(
        code=IpErrorCode.VALIDATION_FAILED,
        message="Duplicate",
        disposition=FailureDisposition.IGNORE,
    )
    assert (
        IpWorkerResultDispositionHandler.to_consumer_action(env, Result.err(ignore_err))
        == ConsumerAction.ACK
    )


def test_disposition_handler_enforces_chunk_precedence_order() -> None:
    env = EventEnvelope(
        id="evt_disp",
        source="ip.data_plane",
        event_type=IpEventType.INBOUND_RECORD_CREATED.value,
        tenant_id="t_01",
        idempotency_key="k_disp",
        payload={},
    )
    retry_err = IpError(
        code=IpErrorCode.EXTERNAL_API_ERROR,
        message="Rate limited",
        disposition=FailureDisposition.RETRY,
    )
    fail_err = IpError(
        code=IpErrorCode.VALIDATION_FAILED,
        message="Poison pill",
        disposition=FailureDisposition.FAIL,
    )
    assert (
        IpWorkerResultDispositionHandler.to_chunk_consumer_action(env, [Result.ok(1), Result.ok(2)])
        == ConsumerAction.ACK
    )
    assert (
        IpWorkerResultDispositionHandler.to_chunk_consumer_action(
            env, [Result.ok(1), Result.err(fail_err)]
        )
        == ConsumerAction.DLQ
    )
    assert (
        IpWorkerResultDispositionHandler.to_chunk_consumer_action(
            env, [Result.ok(1), Result.err(fail_err), Result.err(retry_err)]
        )
        == ConsumerAction.NACK
    )
