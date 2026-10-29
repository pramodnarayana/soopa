"""Comprehensive unit tests for TokenManagerService (L0/L1/L5), DeliverOutboundRecordUseCase (L5), and ExecuteHttpActionStepHandler (L4->L5)."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from types import TracebackType

import pytest
from ip.engine.adapters.outbound.auth.token_refresh_lock import InMemoryTokenRefreshLockAdapter
from ip.engine.adapters.outbound.stitches.step_handlers import ExecuteHttpActionStepHandler
from ip.engine.application.use_cases.connections.token_manager_service import (
    GetValidCredentialsCommand,
    TokenManagerService,
)
from ip.engine.application.use_cases.delivery.deliver_outbound_record_use_case import (
    DeliverOutboundBatchCommand,
    DeliverOutboundRecordCommand,
    DeliverOutboundRecordUseCase,
)
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordCommand,
    FetchRecordUseCase,
)
from ip.engine.domain.constants import DEFAULT_INLINE_THRESHOLD_BYTES, REDACTED_SECRET_VALUE
from ip.engine.domain.enums import (
    AuthType,
    ConnectionStatus,
    FailureDisposition,
    OutboundConflictStrategy,
    OutboundDispatchStatus,
    OutboundFailureCategory,
)
from ip.engine.domain.events import ConnectionErrorRecordedEvent
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    InvalidCredentialsError,
    IpError,
    PayloadNotFoundError,
    Result,
    UpstreamHttpError,
)
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.outbound_record import OutboundRecord
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.connector_port import ConnectorPort
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalization_ledger_repository_port import (
    NormalizationLedgerRepositoryPort,
)
from ip.engine.ports.outbound.normalization_rejection_repository_port import (
    NormalizationRejectionRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.pending_reference_repository_port import (
    PendingReferenceRepositoryPort,
)
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.stream_state_repository_port import StreamStateRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.token_refresh_lock_port import (
    OAuth2TokenRefresherPort,
    RefreshedOAuth2TokensDTO,
)
from ip.engine.ports.outbound.transformation_repository_port import (
    TransformationRepositoryPort,
)
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
)
from ip.engine.ports.types import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    WriteRecordCommand,
    WriteResultDTO,
)
from orchestration.domain.constants import StepFailureCode
from orchestration.domain.failures import RetryableFailure, TerminalFailure
from orchestration.ports.inbound.step_handler_port import StepContext
from security.ports.cipher_port import CipherPort
from seedwork.domain.types import JsonDict, JsonValue


class FakeCipher(CipherPort):
    """Deterministic JSON cipher for testing encrypted credential round-trips."""

    def encrypt_str(self, text: str) -> str:
        return text

    def decrypt_str(self, ciphertext: str) -> str:
        return ciphertext

    def encrypt_dict(self, data: JsonDict) -> bytes:
        return json.dumps(data, sort_keys=True).encode("utf-8")

    def decrypt_dict(self, encrypted_bytes: bytes) -> JsonDict:
        loaded = json.loads(encrypted_bytes.decode("utf-8"))
        assert isinstance(loaded, dict)
        return loaded


class FakeConnectionRepository(ConnectionRepositoryPort):
    def __init__(self) -> None:
        self.connections: dict[str, Connection] = {}

    async def save(
        self, connection: Connection
    ) -> Result[Connection, DuplicateConnectionFingerprintError]:
        self.connections[connection.id] = connection
        return Result.ok(connection)

    async def get_by_id(self, connection_id: str) -> Connection | None:
        return self.connections.get(connection_id)

    async def get_by_id_for_update(self, connection_id: str) -> Connection | None:
        return self.connections.get(connection_id)

    async def get_by_fingerprint(self, tenant_id: str, fingerprint: str) -> Connection | None:
        for c in self.connections.values():
            if c.tenant_id == tenant_id and c.connection_fingerprint == fingerprint:
                return c
        return None

    async def list_by_tenant(
        self, tenant_id: str, status: ConnectionStatus | None = None
    ) -> Sequence[Connection]:
        return [
            c
            for c in self.connections.values()
            if c.tenant_id == tenant_id and (status is None or c.status == status)
        ]


class FakeInboundRecordRepository(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[InboundRecord]:
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
        ]

    async def get_by_external_event_id(
        self, tenant_id: str, connection_id: str, external_event_id: str
    ) -> InboundRecord | None:
        return None


class FakeOutboundRecordRepository(OutboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, OutboundRecord] = {}

    async def save(self, record: OutboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> OutboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[OutboundRecord]:
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
        ]

    async def get_by_idempotency_key(
        self,
        tenant_id: str,
        connection_id: str,
        idempotency_key: str,
    ) -> OutboundRecord | None:
        matches = [
            r
            for r in self.records.values()
            if r.tenant_id == tenant_id
            and r.connection_id == connection_id
            and r.idempotency_key == idempotency_key
        ]
        if not matches:
            return None
        matches.sort(key=lambda r: r.sent_at, reverse=True)
        return matches[0]


class FakeControlPlaneUnitOfWork(IpControlPlaneUnitOfWorkPort):
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: TransformationRepositoryPort
    stitches: StitchRepositoryPort

    def __init__(self) -> None:
        self.connections = FakeConnectionRepository()
        self.commits = 0

    async def __aenter__(self) -> FakeControlPlaneUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


class FakeDataPlaneUnitOfWork(IpDataPlaneUnitOfWorkPort):
    replica_records: ReplicaRecordRepositoryPort
    replica_rejections: ReplicaRejectionRepositoryPort
    entity_maps: GlobalEntityMapRepositoryPort
    normalization_ledger: NormalizationLedgerRepositoryPort
    normalization_rejections: NormalizationRejectionRepositoryPort
    pending_references: PendingReferenceRepositoryPort

    def __init__(self) -> None:
        self.inbound_records = FakeInboundRecordRepository()
        self.outbound_records = FakeOutboundRecordRepository()
        self.commits = 0

    async def __aenter__(self) -> FakeDataPlaneUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass


class FakeTieredStorage(TieredStoragePort):
    def __init__(self, threshold_bytes: int = DEFAULT_INLINE_THRESHOLD_BYTES) -> None:
        self._threshold = threshold_bytes
        self.s3_blobs: dict[str, bytes] = {}

    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonValue | None = None,
    ) -> TieredStorageResultDTO:
        sha256_hex = hashlib.sha256(payload_bytes).hexdigest()
        size = len(payload_bytes)
        if size < self._threshold:
            body: JsonDict | None = parsed_payload if isinstance(parsed_payload, dict) else None
            if body is None:
                try:
                    loaded = json.loads(payload_bytes.decode("utf-8"))
                    if isinstance(loaded, dict):
                        body = loaded
                except ValueError:
                    body = None
            return TieredStorageResultDTO(
                is_inlined=True,
                raw_payload=body,
                s3_key=None,
                payload_size_bytes=size,
                payload_sha256=sha256_hex,
            )
        s3_key = f"tenants/{tenant_id}/traces/{trace_id}/{sha256_hex}.json"
        self.s3_blobs[s3_key] = payload_bytes
        return TieredStorageResultDTO(
            is_inlined=False,
            raw_payload=None,
            s3_key=s3_key,
            payload_size_bytes=size,
            payload_sha256=sha256_hex,
        )

    async def retrieve(self, result: TieredStorageResultDTO) -> Result[bytes, PayloadNotFoundError]:
        if result.is_inlined and result.raw_payload is not None:
            return Result.ok(json.dumps(result.raw_payload).encode("utf-8"))
        if result.s3_key and result.s3_key in self.s3_blobs:
            return Result.ok(self.s3_blobs[result.s3_key])
        return Result.fail(
            PayloadNotFoundError(s3_key=result.s3_key or "missing", message="Not found")
        )


class FakeOAuth2TokenRefresher(OAuth2TokenRefresherPort):
    def __init__(
        self,
        *,
        next_access_tok: str = "rotated_access_v2",
        next_refresh_tok: str | None = "rotated_single_use_v2",
        expires_in_seconds: float = 3600.0,
        failure_error: IpError | None = None,
    ) -> None:
        self.next_access_token = next_access_tok
        self.next_refresh_token = next_refresh_tok
        self.expires_in_seconds = expires_in_seconds
        self.failure_error = failure_error
        self.refresh_calls: int = 0
        self.seen_refresh_tokens: list[str | None] = []

    async def refresh_tokens(
        self,
        *,
        public_config: JsonDict,
        credentials: JsonDict,
        grant_mode: str = "refresh_token",
    ) -> Result[RefreshedOAuth2TokensDTO, IpError]:
        await asyncio.sleep(0.01)
        self.refresh_calls += 1
        raw_rt = credentials.get("refresh_token")
        self.seen_refresh_tokens.append(str(raw_rt) if raw_rt else None)
        if self.failure_error is not None:
            return Result.fail(self.failure_error)
        new_expiry = datetime.now(UTC).timestamp() + self.expires_in_seconds
        return Result.ok(
            RefreshedOAuth2TokensDTO(
                access_token=self.next_access_token,
                refresh_token=self.next_refresh_token,
                expires_at_epoch=new_expiry,
            )
        )


class FakeDestinationAndSourceConnector(ConnectorPort):
    def __init__(self, app_id: str = "sap_isu") -> None:
        self._app_id = app_id
        self.write_calls: list[tuple[WriteRecordCommand, JsonDict]] = []
        self.fetch_calls: list[tuple[str, JsonDict]] = []
        self.queued_write_results: list[WriteResultDTO] = []

    @property
    def app_id(self) -> str:
        return self._app_id

    def spec(self) -> AppSpecDTO:
        return AppSpecDTO(
            app_id=self._app_id,
            display_name="SAP IS-U",
            category="ERP",
            auth_type="OAUTH2",
            description="SAP IS-U Utility ERP",
        )

    async def check(
        self, public_config: JsonDict, credentials: JsonDict
    ) -> ConnectionCheckResultDTO:
        return ConnectionCheckResultDTO.ok("OK")

    async def discover(
        self, connection_id: str, public_config: JsonDict, credentials: JsonDict
    ) -> DiscoveredCatalogDTO:
        return DiscoveredCatalogDTO(connection_id=connection_id)

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
    ) -> Sequence[str]:
        return []

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        if False:
            yield RecordEnvelopeDTO(stream_name=stream_name, record_id="1", data={}, emitted_at="")

    async def fetch_record(
        self,
        stream_name: str,
        record_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> RecordEnvelopeDTO | None:
        self.fetch_calls.append((record_id, dict(credentials)))
        return RecordEnvelopeDTO(
            stream_name=stream_name,
            record_id=record_id,
            data={"id": record_id, "kwh": 105.2},
            emitted_at=datetime.now(UTC).isoformat(),
        )

    async def write_record(
        self,
        stream_name: str,
        command: WriteRecordCommand,
        public_config: JsonDict,
        credentials: JsonDict,
    ) -> WriteResultDTO:
        self.write_calls.append((command, dict(credentials)))
        if self.queued_write_results:
            return self.queued_write_results.pop(0)
        return WriteResultDTO(
            success=True,
            record_id=command.record_id or "rec_1",
            destination_id="SAP-DOC-1001",
            target_url=f"https://sap.grid.local/api/{stream_name}",
            http_method="POST",
            request_headers={
                "Authorization": f"Bearer {credentials.get('access_token', '')}",
                command.idempotency_header_name: command.idempotency_key or "",
            },
            response_status_code=201,
            response_headers={"X-Sap-Tx": "tx-88"},
            response_body={"id": "SAP-DOC-1001", "status": "POSTED"},
            duration_ms=35,
        )


def _seed_oauth2_connection(
    cp_uow: FakeControlPlaneUnitOfWork,
    cipher: FakeCipher,
    *,
    tenant_id: str = "ten_energy_1",
    app_id: str = "sap_isu",
    initial_access_tok: str = "initial_access_v1",
    initial_refresh_tok: str = "initial_refresh_v1",
    expires_offset_seconds: float = 3600.0,
) -> Connection:
    expires_epoch = datetime.now(UTC).timestamp() + expires_offset_seconds
    creds: JsonDict = {
        "client_id": "sap_client",
        "client_secret": "sap_secret",
        "token_url": "https://auth.sap.grid.local/oauth/token",
        "access_token": initial_access_tok,
        "refresh_token": initial_refresh_tok,
        "expires_at_epoch": expires_epoch,
    }
    conn = Connection.create(
        tenant_id=tenant_id,
        app_id=app_id,
        name="SAP IS-U Production",
        auth_type=AuthType.OAUTH2,
        public_config={"base_url": "https://sap.grid.local"},
        encrypted_credentials=cipher.encrypt(creds),
        endpoint_for_fingerprint="https://sap.grid.local",
    )
    conn.activate()
    conn.token_expires_at = datetime.fromtimestamp(expires_epoch, tz=UTC).isoformat()
    cp_uow.connections.connections[conn.id] = conn
    return conn


@pytest.mark.asyncio
async def test_single_token_manager_concurrent_stampede_protection_and_cross_layer_sharing() -> (
    None
):
    """Verifies that 5 concurrent callers sharing one TokenManagerService across L1 and L5
    only invoke the OAuth2 token endpoint ONCE (protecting single-use refresh tokens).
    """
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    lock_adapter = InMemoryTokenRefreshLockAdapter()
    refresher = FakeOAuth2TokenRefresher(
        next_access_tok="fresh_token_v2",
        next_refresh_tok="single_use_refresh_v2",
    )
    # Seed a connection whose token expires in 60s (inside the 900s proactive refresh buffer)
    conn = _seed_oauth2_connection(
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

    # Fire 5 concurrent refresh requests (simulating parallel L1 & L5 workers)
    results = await asyncio.gather(
        *[
            token_manager.get_valid_credentials(
                GetValidCredentialsCommand(
                    tenant_id="ten_energy_1",
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

    # Verify the same single TokenManagerService instance works seamlessly in L1 FetchRecordUseCase
    connector = FakeDestinationAndSourceConnector(app_id="sap_isu")
    storage = FakeTieredStorage()
    l1_fetch_uc = FetchRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors={"sap_isu": connector},
        token_manager=token_manager,
    )
    fetch_res = await l1_fetch_uc.execute(
        FetchRecordCommand(
            tenant_id="ten_energy_1",
            connection_id=conn.id,
            stream_name="meters",
            record_id="MTR-500",
        )
    )
    assert fetch_res.status == "FETCHED"
    assert connector.fetch_calls[0][1]["access_token"] == "fresh_token_v2"
    # Token was already fresh, so no additional refresh call occurred
    assert refresher.refresh_calls == 1


@pytest.mark.asyncio
async def test_token_manager_distinguishes_transient_idp_outage_from_terminal_invalid_grant() -> (
    None
):
    cp_uow = FakeControlPlaneUnitOfWork()
    cipher = FakeCipher()
    transient_conn = _seed_oauth2_connection(
        cp_uow,
        cipher,
        expires_offset_seconds=-10.0,  # Already expired
    )
    # 1. Transient IdP 503 outage -> does NOT poison Connection status to ERROR
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
            tenant_id="ten_energy_1",
            connection_id=transient_conn.id,
        )
    )
    assert transient_res.is_err
    assert transient_conn.status == ConnectionStatus.ACTIVE

    # 2. Terminal invalid_grant (400/401) -> transitions Connection to ERROR and emits event
    terminal_conn = _seed_oauth2_connection(
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
            tenant_id="ten_energy_1",
            connection_id=terminal_conn.id,
        )
    )
    assert res.is_err
    assert terminal_conn.status == ConnectionStatus.ERROR
    assert terminal_conn.last_error_code == "UNAUTHORIZED"
    assert any(isinstance(ev, ConnectionErrorRecordedEvent) for ev in terminal_conn.domain_events)


@pytest.mark.asyncio
async def test_l5_delivery_2_phase_idempotency_reactive_401_and_s3_offload() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorage(threshold_bytes=128)  # Small threshold to test S3 offload
    refresher = FakeOAuth2TokenRefresher(
        next_access_tok="recovered_after_401_token",
        next_refresh_tok="rotated_refresh_after_401",
    )
    # Token appears valid initially (expires in 1 hour), but remote API will return 401 on 1st attempt
    conn = _seed_oauth2_connection(
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
    connector = FakeDestinationAndSourceConnector(app_id="sap_isu")
    large_resp_body: JsonDict = {"id": "SAP-DOC-99", "padding": "X" * 200}
    large_resp_bytes = json.dumps(large_resp_body).encode("utf-8")

    # 1st connector call returns 401; 2nd call (after reactive refresh) returns 201 with >=128B response
    connector.queued_write_results = [
        WriteResultDTO.from_error(
            UpstreamHttpError(status_code=401, message="HTTP 401 Token revoked"),
            response_status_code=401,
            failure_category=OutboundFailureCategory.AUTH_EXPIRED.value,
        ),
        WriteResultDTO(
            success=True,
            record_id="MTR-101",
            destination_id="SAP-DOC-99",
            target_url="https://sap.grid.local/api/meter_readings",
            http_method="POST",
            request_headers={
                "Authorization": "Bearer recovered_after_401_token",
                "Idempotency-Key": "idem-mtr-101",
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
        connectors={"sap_isu": connector},
    )

    large_req_payload: JsonDict = {"meter_id": "MTR-101", "readings": ["R" * 150]}
    cmd = DeliverOutboundRecordCommand(
        tenant_id="ten_energy_1",
        connection_id=conn.id,
        stream_name="meter_readings",
        operation="CREATE",
        payload=large_req_payload,
        record_id="MTR-101",
        idempotency_key="idem-mtr-101",
        correlation_id="MTR-101",
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

    # Verify persisted OutboundRecord has redacted headers and both request & response S3 keys
    saved_record = dp_uow.outbound_records.records[outcome.outbound_record_id]
    assert saved_record.request_s3_key is not None
    assert saved_record.request_body is None
    assert saved_record.response_s3_key is not None
    assert saved_record.response_body is None
    assert saved_record.request_headers["Authorization"] == REDACTED_SECRET_VALUE
    assert saved_record.response_headers is not None
    assert saved_record.response_headers["Set-Cookie"] == REDACTED_SECRET_VALUE

    # ── Phase 2: Re-executing with same idempotency_key short-circuits with ZERO network calls ──
    dedup_res = await use_case.execute(cmd)
    assert dedup_res.is_ok
    assert dedup_res.value is not None
    assert dedup_res.value.was_deduplicated is True
    assert dedup_res.value.outbound_record_id == outcome.outbound_record_id
    assert len(connector.write_calls) == 2  # Still 2!


@pytest.mark.asyncio
async def test_l5_batch_delivery_isolates_items_and_skips_delivered_on_retry() -> None:
    """Proves superiority over n8n's HttpRequestV3 whole-node retry hazard:
    when item #2 fails transiently in a 3-item batch, retrying the batch skips items #0 and #1.
    """
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = _seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=FakeOAuth2TokenRefresher(),
    )
    connector = FakeDestinationAndSourceConnector(app_id="sap_isu")
    # Run 1: Item 0 -> 201, Item 1 -> 201, Item 2 -> 429 Rate Limited
    connector.queued_write_results = [
        WriteResultDTO(
            success=True,
            record_id="MTR-1",
            destination_id="SAP-1",
            response_status_code=201,
        ),
        WriteResultDTO(
            success=True,
            record_id="MTR-2",
            destination_id="SAP-2",
            response_status_code=201,
        ),
        WriteResultDTO.from_error(
            UpstreamHttpError(status_code=429, message="HTTP 429 Rate limit"),
            record_id="MTR-3",
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
        connectors={"sap_isu": connector},
    )

    batch_cmd = DeliverOutboundBatchCommand(
        tenant_id="ten_energy_1",
        connection_id=conn.id,
        stream_name="meters",
        batch_idempotency_prefix="batch_run_100",
        items=[
            DeliverOutboundRecordCommand(
                tenant_id="ten_energy_1",
                connection_id=conn.id,
                stream_name="meters",
                record_id="MTR-1",
                payload={"id": "MTR-1"},
            ),
            DeliverOutboundRecordCommand(
                tenant_id="ten_energy_1",
                connection_id=conn.id,
                stream_name="meters",
                record_id="MTR-2",
                payload={"id": "MTR-2"},
            ),
            DeliverOutboundRecordCommand(
                tenant_id="ten_energy_1",
                connection_id=conn.id,
                stream_name="meters",
                record_id="MTR-3",
                payload={"id": "MTR-3"},
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

    # Run 2 (Retry): Items 0 and 1 are deduplicated; only Item 2 hits the network!
    connector.queued_write_results = [
        WriteResultDTO(
            success=True,
            record_id="MTR-3",
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
    assert len(connector.write_calls) == 4  # Only 1 additional network call (for MTR-3)!


@pytest.mark.asyncio
async def test_l4_to_l5_execute_http_action_step_handler_and_crash_reconciliation() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    conn = _seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=FakeOAuth2TokenRefresher(),
    )
    connector = FakeDestinationAndSourceConnector(app_id="sap_isu")
    use_case = DeliverOutboundRecordUseCase(
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
        token_manager=token_manager,
        connectors={"sap_isu": connector},
    )
    handler = ExecuteHttpActionStepHandler(
        delivery_executor=use_case,
        outbound_lookup=dp_uow.outbound_records,
    )

    step_ctx = StepContext(
        tenant_id="ten_energy_1",
        run_id="wfr_1",
        step_run_id="wsr_1",
        node_key="push_to_sap",
        retry_count=0,
        app_retry_count=0,
        internal_retry_count=0,
        idempotency_key="wfr_1:push_to_sap",
        trace_id="ip_trc_stitch_1",
        correlation_id="MTR-777",
        deadline=datetime.now(UTC),
    )
    step_input: JsonDict = {
        "connection_id": conn.id,
        "stream_name": "meter_readings",
        "operation": "UPSERT",
        "record_id": "MTR-777",
        "payload": {"meter_id": "MTR-777", "kwh": 88.4},
        "conflict_strategy": OutboundConflictStrategy.IDEMPOTENT_SUCCESS.value,
    }

    # 1. Simulate HTTP 429 Rate Limit -> returns RetryableFailure(RATE_LIMITED, is_app_error=False)
    connector.queued_write_results = [
        WriteResultDTO.from_error(
            UpstreamHttpError(status_code=429, message="Rate limit exceeded"),
            record_id="MTR-777",
            response_status_code=429,
            response_headers={"Retry-After": "25"},
            retry_after_seconds=25,
            failure_category=OutboundFailureCategory.RATE_LIMITED.value,
        )
    ]
    rate_limit_res = await handler.execute(step_ctx, step_input)
    assert rate_limit_res.is_err
    err_429 = rate_limit_res.unwrap_err()
    assert isinstance(err_429, RetryableFailure)
    assert err_429.code is StepFailureCode.RATE_LIMITED
    assert err_429.is_app_error is False
    assert err_429.retry_after is not None
    assert int(err_429.retry_after.total_seconds()) == 25

    # 2. Simulate HTTP 422 Validation Error -> returns TerminalFailure(VALIDATION_REJECTED)
    connector.queued_write_results = [
        WriteResultDTO.from_error(
            UpstreamHttpError(status_code=422, message="Invalid meter UOM"),
            record_id="MTR-777",
            response_status_code=422,
            failure_category=OutboundFailureCategory.VALIDATION_ERROR.value,
        )
    ]
    val_res = await handler.execute(step_ctx, step_input)
    assert val_res.is_err
    err_422 = val_res.unwrap_err()
    assert isinstance(err_422, TerminalFailure)
    assert err_422.code is StepFailureCode.VALIDATION_REJECTED

    # 3. Simulate successful delivery followed by worker crash before L4 step completion
    connector.queued_write_results = [
        WriteResultDTO(
            success=True,
            record_id="MTR-777",
            destination_id="SAP-777",
            response_status_code=200,
            response_body={"sap_doc": "SAP-777"},
        )
    ]
    ok_res = await handler.execute(step_ctx, step_input)
    assert ok_res.is_ok
    output_payload = ok_res.unwrap()
    assert output_payload["destination_id"] == "SAP-777"

    # When ReapExpiredLeasesUseCase calls handler.reconcile(), it adopts the DELIVERED OutboundRecord!
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
    conn = _seed_oauth2_connection(cp_uow, cipher, expires_offset_seconds=3600.0)
    token_manager = TokenManagerService(
        control_plane_uow=cp_uow,
        cipher=cipher,
        lock_port=InMemoryTokenRefreshLockAdapter(),
        token_refresher=FakeOAuth2TokenRefresher(),
    )
    connector = FakeDestinationAndSourceConnector(app_id="sap_isu")
    use_case = DeliverOutboundRecordUseCase(
        data_plane_uow=dp_uow,
        tiered_storage=FakeTieredStorage(),
        token_manager=token_manager,
        connectors={"sap_isu": connector},
    )

    cmd = DeliverOutboundRecordCommand(
        tenant_id="ten_energy_1",
        connection_id=conn.id,
        stream_name="meter_readings",
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

    # The connector received the raw headers
    assert len(connector.write_calls) == 1
    write_cmd, _ = connector.write_calls[0]
    assert write_cmd.headers["X-Client-Secret"] == "super_secret_caller_value"
    assert write_cmd.headers["Authorization"] == "Bearer caller_raw_token"

    # But the persisted OutboundRecord has caller-supplied headers redacted
    assert res.value is not None
    saved = dp_uow.outbound_records.records[res.value.outbound_record_id]
    assert saved.request_headers["X-Client-Secret"] == "***REDACTED***"
    assert saved.request_headers["Authorization"] == "***REDACTED***"
    assert saved.request_headers["Idempotency-Key"] == "idem-secret-headers-1"
