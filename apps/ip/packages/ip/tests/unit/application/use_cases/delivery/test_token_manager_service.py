"""Unit tests for TokenManagerService single-flight OAuth2 refresh and error classification."""

from __future__ import annotations

import asyncio

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
from ip.engine.application.use_cases.connections.token_manager_service import (
    GetValidCredentialsCommand,
    TokenManagerService,
)
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordCommand,
    FetchRecordUseCase,
)
from ip.engine.domain.connection.enums import ConnectionStatus
from ip.engine.domain.connection.events import ConnectionErrorRecordedEvent
from ip.engine.domain.dispatch.enums import FailureDisposition
from ip.engine.domain.exceptions import InvalidCredentialsError, UpstreamHttpError


@pytest.mark.asyncio
async def test_token_manager_prevents_concurrent_refresh_stampede() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    cipher = FakeCipher()
    lock_adapter = InMemoryTokenRefreshLockAdapter()
    refresher = FakeOAuth2TokenRefresher(
        next_access_tok="fresh_token_v2",
        next_refresh_tok="single_use_refresh_v2",
    )
    conn = seed_oauth2_connection(
        cp_uow,
        cipher,
        initial_access_tok="expiring_token_v1",
        initial_refresh_tok="single_use_refresh_v1",
        expires_offset_seconds=60.0,
    )

    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=lock_adapter,
        token_refresher=refresher,
    )

    results = await asyncio.gather(
        *[
            token_manager.get_valid_credentials(
                GetValidCredentialsCommand(
                    tenant_id="ten_alpha_1",
                    connection_id=conn.id,
                )
            )
            for _ in range(5)
        ]
    )

    assert refresher.refresh_calls == 1
    for res in results:
        assert res.is_ok
        assert res.value is not None
        assert res.value.credentials["access_token"] == "fresh_token_v2"
        assert res.value.credentials["refresh_token"] == "single_use_refresh_v2"


@pytest.mark.asyncio
async def test_token_manager_shares_refreshed_credentials_with_fetch_record_use_case() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    refresher = FakeOAuth2TokenRefresher(
        next_access_tok="fresh_token_v2",
        next_refresh_tok="single_use_refresh_v2",
    )
    conn = seed_oauth2_connection(
        cp_uow,
        cipher,
        initial_access_tok="expiring_token_v1",
        initial_refresh_tok="single_use_refresh_v1",
        expires_offset_seconds=60.0,
    )
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=refresher,
    )
    connector = FakeBidirectionalConnector(app_id="globex_dest")
    l1_fetch_uc = FetchRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
        cipher=cipher,
        connectors={"globex_dest": connector},
        token_manager=token_manager,
    )

    fetch_res = await l1_fetch_uc.execute(
        FetchRecordCommand(
            tenant_id="ten_alpha_1",
            connection_id=conn.id,
            stream_name="records_alpha",
            record_id="REC-500",
        )
    )
    assert fetch_res.status == "FETCHED"
    assert connector.fetch_calls[0][1]["access_token"] == "fresh_token_v2"
    assert refresher.refresh_calls == 1


@pytest.mark.asyncio
async def test_token_manager_preserves_active_status_on_transient_idp_outage() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    cipher = FakeCipher()
    transient_conn = seed_oauth2_connection(
        cp_uow,
        cipher,
        expires_offset_seconds=-10.0,
    )
    transient_refresher = FakeOAuth2TokenRefresher(
        failure_error=UpstreamHttpError(
            status_code=503,
            message="IdP 503 Service Unavailable",
            disposition=FailureDisposition.RETRY,
        )
    )
    transient_tm = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=transient_refresher,
    )

    transient_res = await transient_tm.get_valid_credentials(
        GetValidCredentialsCommand(
            tenant_id="ten_alpha_1",
            connection_id=transient_conn.id,
        )
    )
    assert transient_res.is_err
    assert transient_conn.status == ConnectionStatus.ACTIVE


@pytest.mark.asyncio
async def test_token_manager_marks_connection_error_on_terminal_invalid_grant() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    cipher = FakeCipher()
    terminal_conn = seed_oauth2_connection(
        cp_uow,
        cipher,
        expires_offset_seconds=-10.0,
    )
    terminal_refresher = FakeOAuth2TokenRefresher(
        failure_error=InvalidCredentialsError(
            field_name="refresh_token",
            message="OAuth2 invalid_grant: refresh token revoked or expired",
        )
    )
    terminal_tm = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=terminal_refresher,
    )

    res = await terminal_tm.get_valid_credentials(
        GetValidCredentialsCommand(
            tenant_id="ten_alpha_1",
            connection_id=terminal_conn.id,
        )
    )
    assert res.is_err
    assert terminal_conn.status == ConnectionStatus.ERROR
    assert terminal_conn.last_error_code == "UNAUTHORIZED"
    assert any(isinstance(ev, ConnectionErrorRecordedEvent) for ev in terminal_conn.domain_events)
