"""Unit tests for DeliverOutboundRecordUseCase (L5) and ExecuteHttpActionStepHandler (L4->L5)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from helpers.delivery_fakes import (
    FakeBidirectionalConnector,
    FakeCipher,
    FakeControlPlaneUnitOfWork,
    FakeDataPlaneUnitOfWork,
    FakeOAuth2TokenRefresher,
    FakeTieredStorage,
    seed_oauth2_connection,
)
from ip.engine.adapters.outbound.auth.token_refresh_lock import InMemoryTokenRefreshLockAdapter
from ip.engine.adapters.outbound.stitches.step_handlers import ExecuteHttpActionStepHandler
from ip.engine.application.use_cases.connections.token_manager_service import TokenManagerService
from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundBatchCommand,
    DeliverOutboundRecordCommand,
    DeliverOutboundRecordUseCase,
)
from ip.engine.domain.constants import REDACTED_SECRET_VALUE
from ip.engine.domain.dispatch.enums import (
    OutboundConflictStrategy,
    OutboundDispatchStatus,
    OutboundFailureCategory,
)
from ip.engine.domain.exceptions import UpstreamHttpError
from ip.engine.ports.outbound.connector_port import WriteResultDTO
from orchestration.domain.constants import StepFailureCode
from orchestration.domain.failures import RetryableFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext
from seedwork.domain.types import JsonDict


def _make_step_context() -> StepContext:
    return StepContext(
        tenant_id="ten_alpha_1",
        run_id="wfr_1",
        step_run_id="wsr_1",
        node_key="push_to_globex",
        retry_count=0,
        app_retry_count=0,
        internal_retry_count=0,
        idempotency_key="wfr_1:push_to_globex",
        trace_id="ip_trc_stitch_1",
        correlation_id="REC-777",
        deadline=datetime.now(UTC),
    )


def _make_step_input(connection_id: str) -> JsonDict:
    return {
        "connection_id": connection_id,
        "stream_name": "records_alpha",
        "operation": "UPSERT",
        "record_id": "REC-777",
        "payload": {"record_id": "REC-777", "amount": 88.4},
        "conflict_strategy": OutboundConflictStrategy.IDEMPOTENT_SUCCESS.value,
    }


@pytest.mark.asyncio
async def test_l5_delivery_recovers_from_reactive_401_with_s3_payload_offload() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorage(threshold_bytes=128)
    refresher = FakeOAuth2TokenRefresher(
        next_access_tok="recovered_after_401_token",
        next_refresh_tok="rotated_refresh_after_401",
    )
    conn = seed_oauth2_connection(
        cp_uow,
        cipher,
        initial_access_tok="revoked_early_token",
        expires_offset_seconds=3600.0,
    )
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=refresher,
    )
    connector = FakeBidirectionalConnector(app_id="globex_dest")
    large_resp_body: JsonDict = {"id": "SAP-DOC-99", "padding": "X" * 200}
    large_resp_bytes = json.dumps(large_resp_body).encode("utf-8")

    connector.queued_write_results = [
        WriteResultDTO.from_error(
            UpstreamHttpError(status_code=401, message="HTTP 401 Token revoked"),
            response_status_code=401,
            failure_category=OutboundFailureCategory.AUTH_EXPIRED.value,
        ),
        WriteResultDTO(
            success=True,
            record_id="REC-101",
            destination_id="SAP-DOC-99",
            target_url="https://globex.local/api/records_alpha",
            http_method="POST",
            request_headers={
                "Authorization": "Bearer recovered_after_401_token",
                "Idempotency-Key": "idem-rec-101",
            },
            response_status_code=201,
            response_headers={"Set-Cookie": "sap_sess=secret"},
            response_body=large_resp_body,
            raw_response_bytes=large_resp_bytes,
            duration_ms=42,
        ),
    ]

    use_case = DeliverOutboundRecordUseCase(
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        token_manager=token_manager,
        connectors={"globex_dest": connector},
    )

    large_req_payload: JsonDict = {"record_id": "REC-101", "entries": ["R" * 150]}
    cmd = DeliverOutboundRecordCommand(
        tenant_id="ten_alpha_1",
        connection_id=conn.id,
        stream_name="records_alpha",
        operation="CREATE",
        payload=large_req_payload,
        record_id="REC-101",
        idempotency_key="idem-rec-101",
        correlation_id="REC-101",
    )

    res = await use_case.execute(cmd)
    assert res.is_ok
    assert res.value is not None
    outcome = res.value
    assert outcome.status is OutboundDispatchStatus.DELIVERED
    assert outcome.was_token_refreshed is True
    assert outcome.was_deduplicated is False
    assert outcome.destination_id == "SAP-DOC-99"
    assert outcome.response_s3_key is not None
    assert len(connector.write_calls) == 2
    assert connector.write_calls[0][1]["access_token"] == "revoked_early_token"
    assert connector.write_calls[1][1]["access_token"] == "recovered_after_401_token"

    saved_record = dp_uow.outbound_records.records[outcome.outbound_record_id]
    assert saved_record.request_s3_key is not None
    assert saved_record.request_body is None
    assert saved_record.response_s3_key is not None
    assert saved_record.response_body is None
    assert saved_record.request_headers["Authorization"] == REDACTED_SECRET_VALUE
    assert saved_record.response_headers is not None
    assert saved_record.response_headers["Set-Cookie"] == REDACTED_SECRET_VALUE


@pytest.mark.asyncio
async def test_l5_delivery_deduplicates_repeated_idempotency_key_without_network_calls() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=FakeOAuth2TokenRefresher(),
    )
    connector = FakeBidirectionalConnector(app_id="globex_dest")
    use_case = DeliverOutboundRecordUseCase(
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
        token_manager=token_manager,
        connectors={"globex_dest": connector},
    )

    cmd = DeliverOutboundRecordCommand(
        tenant_id="ten_alpha_1",
        connection_id=conn.id,
        stream_name="records_alpha",
        operation="CREATE",
        payload={"record_id": "REC-101"},
        record_id="REC-101",
        idempotency_key="idem-rec-101",
    )
    first_res = await use_case.execute(cmd)
    assert first_res.is_ok
    assert first_res.value is not None

    dedup_res = await use_case.execute(cmd)
    assert dedup_res.is_ok
    assert dedup_res.value is not None
    assert dedup_res.value.was_deduplicated is True
    assert dedup_res.value.outbound_record_id == first_res.value.outbound_record_id
    assert len(connector.write_calls) == 1


@pytest.mark.asyncio
async def test_l5_batch_delivery_skips_already_delivered_items_on_retry() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=FakeOAuth2TokenRefresher(),
    )
    connector = FakeBidirectionalConnector(app_id="globex_dest")
    connector.queued_write_results = [
        WriteResultDTO(
            success=True,
            record_id="REC-1",
            destination_id="SAP-1",
            response_status_code=201,
        ),
        WriteResultDTO(
            success=True,
            record_id="REC-2",
            destination_id="SAP-2",
            response_status_code=201,
        ),
        WriteResultDTO.from_error(
            UpstreamHttpError(status_code=429, message="HTTP 429 Rate limit"),
            record_id="REC-3",
            response_status_code=429,
            response_headers={"Retry-After": "15"},
            retry_after_seconds=15,
            failure_category=OutboundFailureCategory.RATE_LIMITED.value,
        ),
    ]

    use_case = DeliverOutboundRecordUseCase(
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
        token_manager=token_manager,
        connectors={"globex_dest": connector},
    )

    batch_cmd = DeliverOutboundBatchCommand(
        tenant_id="ten_alpha_1",
        connection_id=conn.id,
        stream_name="records_alpha",
        batch_idempotency_prefix="batch_run_100",
        items=[
            DeliverOutboundRecordCommand(
                tenant_id="ten_alpha_1",
                connection_id=conn.id,
                stream_name="records_alpha",
                record_id="REC-1",
                payload={"id": "REC-1"},
            ),
            DeliverOutboundRecordCommand(
                tenant_id="ten_alpha_1",
                connection_id=conn.id,
                stream_name="records_alpha",
                record_id="REC-2",
                payload={"id": "REC-2"},
            ),
            DeliverOutboundRecordCommand(
                tenant_id="ten_alpha_1",
                connection_id=conn.id,
                stream_name="records_alpha",
                record_id="REC-3",
                payload={"id": "REC-3"},
            ),
        ],
    )

    first_batch_res = await use_case.execute_batch(batch_cmd)
    assert first_batch_res.is_ok
    assert first_batch_res.value is not None
    assert first_batch_res.value.delivered_count == 2
    assert first_batch_res.value.retry_scheduled_count == 1
    assert first_batch_res.value.results[2].retry_after_seconds == 15
    assert len(connector.write_calls) == 3

    connector.queued_write_results = [
        WriteResultDTO(
            success=True,
            record_id="REC-3",
            destination_id="SAP-3",
            response_status_code=201,
        )
    ]
    second_batch_res = await use_case.execute_batch(batch_cmd)
    assert second_batch_res.is_ok
    assert second_batch_res.value is not None
    assert second_batch_res.value.delivered_count == 3
    assert second_batch_res.value.deduplicated_count == 2
    assert second_batch_res.value.retry_scheduled_count == 0
    assert len(connector.write_calls) == 4


@pytest.mark.asyncio
async def test_execute_http_action_step_handler_maps_429_to_retryable_failure() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=FakeOAuth2TokenRefresher(),
    )
    connector = FakeBidirectionalConnector(app_id="globex_dest")
    connector.queued_write_results = [
        WriteResultDTO.from_error(
            UpstreamHttpError(status_code=429, message="Rate limit exceeded"),
            record_id="REC-777",
            response_status_code=429,
            response_headers={"Retry-After": "25"},
            retry_after_seconds=25,
            failure_category=OutboundFailureCategory.RATE_LIMITED.value,
        )
    ]
    use_case = DeliverOutboundRecordUseCase(
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
        token_manager=token_manager,
        connectors={"globex_dest": connector},
    )
    handler = ExecuteHttpActionStepHandler(
        delivery_executor=use_case,
        outbound_lookup=dp_uow.outbound_records,
    )

    rate_limit_res = await handler.execute(_make_step_context(), _make_step_input(conn.id))
    assert rate_limit_res.is_err
    err_429 = rate_limit_res.unwrap_err()
    assert isinstance(err_429, RetryableFailure)
    assert err_429.code is StepFailureCode.RATE_LIMITED
    assert err_429.is_app_error is False
    assert err_429.retry_after is not None
    assert int(err_429.retry_after.total_seconds()) == 25


@pytest.mark.asyncio
async def test_execute_http_action_step_handler_maps_422_to_terminal_failure() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=FakeOAuth2TokenRefresher(),
    )
    connector = FakeBidirectionalConnector(app_id="globex_dest")
    connector.queued_write_results = [
        WriteResultDTO.from_error(
            UpstreamHttpError(status_code=422, message="Invalid record schema"),
            record_id="REC-777",
            response_status_code=422,
            failure_category=OutboundFailureCategory.VALIDATION_ERROR.value,
        )
    ]
    use_case = DeliverOutboundRecordUseCase(
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
        token_manager=token_manager,
        connectors={"globex_dest": connector},
    )
    handler = ExecuteHttpActionStepHandler(
        delivery_executor=use_case,
        outbound_lookup=dp_uow.outbound_records,
    )

    val_res = await handler.execute(_make_step_context(), _make_step_input(conn.id))
    assert val_res.is_err
    err_422 = val_res.unwrap_err()
    assert isinstance(err_422, TerminalFailure)
    assert err_422.code is StepFailureCode.VALIDATION_REJECTED


@pytest.mark.asyncio
async def test_execute_http_action_step_handler_reconciles_delivered_record_after_crash() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=FakeOAuth2TokenRefresher(),
    )
    connector = FakeBidirectionalConnector(app_id="globex_dest")
    connector.queued_write_results = [
        WriteResultDTO(
            success=True,
            record_id="REC-777",
            destination_id="SAP-777",
            response_status_code=200,
            response_body={"sap_doc": "SAP-777"},
        )
    ]
    use_case = DeliverOutboundRecordUseCase(
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
        token_manager=token_manager,
        connectors={"globex_dest": connector},
    )
    handler = ExecuteHttpActionStepHandler(
        delivery_executor=use_case,
        outbound_lookup=dp_uow.outbound_records,
    )

    step_ctx = _make_step_context()
    step_input = _make_step_input(conn.id)
    ok_res = await handler.execute(step_ctx, step_input)
    assert ok_res.is_ok
    assert ok_res.unwrap()["destination_id"] == "SAP-777"

    reconcile_res = await handler.reconcile(step_ctx, step_input)
    assert reconcile_res.is_ok
    reconcile_outcome = reconcile_res.unwrap()
    assert reconcile_outcome.found is True
    assert reconcile_outcome.adopted_output is not None
    assert reconcile_outcome.adopted_output["destination_id"] == "SAP-777"
    assert reconcile_outcome.adopted_output["was_deduplicated"] is True


@pytest.mark.asyncio
async def test_deliver_outbound_record_redacts_caller_supplied_headers_in_ledger() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=FakeOAuth2TokenRefresher(),
    )
    connector = FakeBidirectionalConnector(app_id="globex_dest")
    use_case = DeliverOutboundRecordUseCase(
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
        token_manager=token_manager,
        connectors={"globex_dest": connector},
    )

    cmd = DeliverOutboundRecordCommand(
        tenant_id="ten_alpha_1",
        connection_id=conn.id,
        stream_name="records_alpha",
        operation="CREATE",
        payload={"reading": 450},
        record_id="REC-999",
        idempotency_key="idem-secret-headers-1",
        headers={
            "X-Client-Secret": "super_secret_caller_value",
            "Authorization": "Bearer caller_raw_token",
            "X-Trace-Tag": "visible_tag",
        },
    )

    connector.queued_write_results = [
        WriteResultDTO(
            success=True,
            record_id="REC-999",
            destination_id="EXT-999",
            response_status_code=200,
        )
    ]

    res = await use_case.execute(cmd)
    assert res.is_ok

    assert len(connector.write_calls) == 1
    write_cmd, _ = connector.write_calls[0]
    assert write_cmd.headers["X-Client-Secret"] == "super_secret_caller_value"
    assert write_cmd.headers["Authorization"] == "Bearer caller_raw_token"

    assert res.value is not None
    saved = dp_uow.outbound_records.records[res.value.outbound_record_id]
    assert saved.request_headers["X-Client-Secret"] == REDACTED_SECRET_VALUE
    assert saved.request_headers["Authorization"] == REDACTED_SECRET_VALUE
    assert saved.request_headers["Idempotency-Key"] == "idem-secret-headers-1"
