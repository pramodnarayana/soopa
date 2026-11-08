"""Unit tests for StageOutboundDeliveryUseCase verifying pure L4->L5 Egress queue staging."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from helpers.delivery_fakes import (
    FakeCipher,
    FakeControlPlaneUnitOfWork,
    FakeDataPlaneUnitOfWork,
    FakeTieredStorage,
    seed_oauth2_connection,
)
from ip.engine.adapters.outbound.stitches.step_handlers import ExecuteHttpActionStepHandler
from ip.engine.application.use_cases.delivery.stage_outbound_delivery_use_case import (
    StageOutboundDeliveryCommand,
    StageOutboundDeliveryUseCase,
)
from ip.engine.domain.dispatch.enums import OutboundConflictStrategy, OutboundDispatchStatus
from ip.engine.domain.dispatch.events import OutboundRecordCreatedEvent
from orchestration.ports.inbound.step_handler_port import StepContext
from seedwork.domain.types import JsonDict


def _make_step_context() -> StepContext:
    return StepContext(
        tenant_id="ten_alpha_1",
        run_id="wfr_stage_1",
        step_run_id="wsr_stage_1",
        node_key="stage_to_dest",
        retry_count=0,
        app_retry_count=0,
        internal_retry_count=0,
        idempotency_key="wfr_stage_1:stage_to_dest",
        trace_id="ip_trc_stage_1",
        correlation_id="REC-901",
        deadline=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_stage_outbound_delivery_persists_pending_record_without_http_calls() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    storage = FakeTieredStorage()

    stager = StageOutboundDeliveryUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
    )
    res = await stager.execute(
        StageOutboundDeliveryCommand(
            tenant_id="ten_alpha_1",
            connection_id=conn.id,
            stream_name="orders",
            operation="UPSERT",
            payload={"id": "ORD-901", "amount": 120.5},
            record_id="ORD-901",
            idempotency_key="idem-ord-901",
            headers={"Authorization": "Bearer secret_inline_token"},
            trace_id="ip_trc_stage_1",
            correlation_id="ORD-901",
            causation_depth=1,
        )
    )

    assert res.is_ok
    dto = res.unwrap()
    assert dto.status is OutboundDispatchStatus.PENDING
    assert dto.was_deduplicated is False
    assert len(dp_uow.outbound_records.records) == 1
    saved = dp_uow.outbound_records.records[dto.outbound_record_id]
    assert saved.status is OutboundDispatchStatus.PENDING
    assert saved.app_id == "globex_dest"
    assert saved.idempotency_key == "idem-ord-901"
    outbox_events = [
        e for e in dp_uow.outbound_records.events if isinstance(e, OutboundRecordCreatedEvent)
    ]
    assert len(outbox_events) == 1
    assert outbox_events[0].status == OutboundDispatchStatus.PENDING.value


@pytest.mark.asyncio
async def test_stage_outbound_delivery_deduplicates_existing_idempotency_key() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    stager = StageOutboundDeliveryUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
    )
    cmd = StageOutboundDeliveryCommand(
        tenant_id="ten_alpha_1",
        connection_id=conn.id,
        stream_name="orders",
        operation="CREATE",
        payload={"id": "ORD-902"},
        idempotency_key="idem-ord-902",
        trace_id="ip_trc_stage_2",
    )
    first_res = await stager.execute(cmd)
    assert first_res.is_ok
    second_res = await stager.execute(cmd)
    assert second_res.is_ok
    second_dto = second_res.unwrap()
    assert second_dto.was_deduplicated is True
    assert second_dto.outbound_record_id == first_res.unwrap().outbound_record_id
    assert len(dp_uow.outbound_records.records) == 1
    outbox_events = [
        e for e in dp_uow.outbound_records.events if isinstance(e, OutboundRecordCreatedEvent)
    ]
    assert len(outbox_events) == 1


@pytest.mark.asyncio
async def test_stage_outbound_delivery_offloads_large_payload_to_tiered_storage() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    storage = FakeTieredStorage(threshold_bytes=64)
    stager = StageOutboundDeliveryUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
    )
    large_payload: JsonDict = {"id": "ORD-BIG", "blob": "Z" * 200}
    res = await stager.execute(
        StageOutboundDeliveryCommand(
            tenant_id="ten_alpha_1",
            connection_id=conn.id,
            stream_name="orders",
            operation="CREATE",
            payload=large_payload,
            idempotency_key="idem-ord-big",
            trace_id="ip_trc_stage_big",
        )
    )
    assert res.is_ok
    dto = res.unwrap()
    saved = dp_uow.outbound_records.records[dto.outbound_record_id]
    assert saved.request_body is None
    assert saved.request_s3_key is not None


@pytest.mark.asyncio
async def test_execute_http_action_step_handler_stages_egress_record_purely() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    stager = StageOutboundDeliveryUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
    )
    handler = ExecuteHttpActionStepHandler(
        delivery_stager=stager,
        outbound_lookup=dp_uow.outbound_records,
    )
    step_ctx = _make_step_context()
    step_input: JsonDict = {
        "connection_id": conn.id,
        "stream_name": "orders",
        "operation": "UPSERT",
        "record_id": "REC-901",
        "payload": {"record_id": "REC-901", "amount": 55.0},
        "conflict_strategy": OutboundConflictStrategy.IDEMPOTENT_SUCCESS.value,
    }
    step_res = await handler.execute(step_ctx, step_input)
    assert step_res.is_ok
    output = step_res.unwrap()
    assert output["status"] == OutboundDispatchStatus.PENDING.value
    assert output["was_deduplicated"] is False

    reconcile_res = await handler.reconcile(step_ctx, step_input)
    assert reconcile_res.is_ok
    reconcile_outcome = reconcile_res.unwrap()
    assert reconcile_outcome.found is True
    assert reconcile_outcome.adopted_output is not None
    assert reconcile_outcome.adopted_output["outbound_record_id"] == output["outbound_record_id"]
