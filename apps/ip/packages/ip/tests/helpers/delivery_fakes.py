"""Shared pure in-memory test fakes for outbound delivery and token manager unit tests."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from types import TracebackType

from ip.engine.domain.connection.catalog import ConnectionCatalog
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.constants import DEFAULT_INLINE_THRESHOLD_BYTES
from ip.engine.domain.dispatch.outbound_record import OutboundRecord
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    IpError,
    PayloadNotFoundError,
    Result,
)
from ip.engine.domain.normalization.transformation import Transformation
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.stream_state import ConnectionStreamState
from ip.engine.domain.replication.sync_run import SyncRun
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.connector_port import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    ConnectorPort,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    WriteRecordCommand,
    WriteResultDTO,
)
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
from security.ports.cipher_port import CipherPort
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope
from strace.ports import TraceRepositoryPort

from helpers.trace_fakes import (
    DummyEntityMapRepo,
    DummyLedgerRepo,
    DummyNormRejectionRepo,
    DummyPendingRefRepo,
    DummyReplicaRejectionRepo,
    InMemoryNormalizedRecordRepo,
    InMemoryReplicaRecordRepo,
    InMemoryTraceRepo,
)


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

    async def delete(self, connection: Connection) -> None:
        self.connections.pop(connection.id, None)

    async def delete_by_id(self, connection_id: str) -> None:
        self.connections.pop(connection_id, None)


class FakeInboundRecordRepository(InboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, InboundRecord] = {}

    async def save(self, record: InboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> InboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
        *,
        hydrate_payloads: bool = False,
    ) -> Sequence[InboundRecord]:
        _ = hydrate_payloads
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
        ]

    async def get_by_external_event_id(
        self, tenant_id: str, connection_id: str, external_event_id: str
    ) -> InboundRecord | None:
        return None

    async def list_records(
        self,
        tenant_id: str,
        *,
        connection_id: str | None = None,
        stream_name: str | None = None,
        limit: int = 50,
        offset: int = 0,
        hydrate_payloads: bool = False,
    ) -> Sequence[InboundRecord]:
        _ = hydrate_payloads
        res = [
            r
            for r in self.records.values()
            if r.tenant_id == tenant_id
            and (connection_id is None or r.connection_id == connection_id)
            and (stream_name is None or r.stream_name == stream_name)
        ]
        return res[offset : offset + limit]


class FakeOutboundRecordRepository(OutboundRecordRepositoryPort):
    def __init__(self) -> None:
        self.records: dict[str, OutboundRecord] = {}

    async def save(self, record: OutboundRecord) -> None:
        self.records[record.id] = record

    async def get_by_id(self, record_id: str, tenant_id: str) -> OutboundRecord | None:
        rec = self.records.get(record_id)
        return rec if rec and rec.tenant_id == tenant_id else None

    async def get_by_trace_id(
        self,
        trace_id: str,
        tenant_id: str,
        *,
        hydrate_payloads: bool = False,
    ) -> Sequence[OutboundRecord]:
        _ = hydrate_payloads
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


class DummyCatalogRepo(CatalogRepositoryPort):
    async def save(self, catalog: ConnectionCatalog) -> None:
        _ = catalog

    async def get_active_by_connection_id(self, connection_id: str) -> ConnectionCatalog | None:
        _ = connection_id
        return None

    async def get_by_version(self, connection_id: str, version: int) -> ConnectionCatalog | None:
        _ = (connection_id, version)
        return None


class DummyStreamStateRepo(StreamStateRepositoryPort):
    async def get_by_stream(
        self, tenant_id: str, connection_id: str, stream_name: str
    ) -> ConnectionStreamState | None:
        _ = (tenant_id, connection_id, stream_name)
        return None

    async def list_by_connection(
        self, tenant_id: str, connection_id: str
    ) -> Sequence[ConnectionStreamState]:
        _ = (tenant_id, connection_id)
        return ()

    async def save(self, state: ConnectionStreamState) -> None:
        _ = state


class DummySyncRunRepo(SyncRunRepositoryPort):
    async def get_by_id(self, run_id: str, tenant_id: str) -> SyncRun | None:
        _ = (run_id, tenant_id)
        return None

    async def get_active_run(
        self,
        connection_id: str,
        stream: str,
        tenant_id: str | None = None,
        for_update: bool = False,
    ) -> SyncRun | None:
        _ = (connection_id, stream, tenant_id, for_update)
        return None

    async def get_latest_generation_id(
        self, tenant_id: str, connection_id: str, stream: str
    ) -> int:
        _ = (tenant_id, connection_id, stream)
        return 1

    async def list_by_connection(
        self, tenant_id: str, connection_id: str, limit: int = 50
    ) -> Sequence[SyncRun]:
        _ = (tenant_id, connection_id, limit)
        return ()

    async def save(self, run: SyncRun) -> None:
        _ = run


class DummyTransformationRepo(TransformationRepositoryPort):
    async def get_by_stream(
        self, *, tenant_id: str, connection_id: str, stream: str
    ) -> Transformation | None:
        _ = (tenant_id, connection_id, stream)
        return None

    async def save(self, transformation: Transformation) -> None:
        _ = transformation

    async def list_by_connection(
        self, *, tenant_id: str, connection_id: str
    ) -> list[Transformation]:
        _ = (tenant_id, connection_id)
        return []


class DummyStitchRepo(StitchRepositoryPort):
    async def save(self, stitch: Stitch) -> None:
        _ = stitch

    async def get_by_id(self, *, tenant_id: str, stitch_id: str) -> Stitch | None:
        _ = (tenant_id, stitch_id)
        return None

    async def get_by_id_global(self, *, stitch_id: str) -> Stitch | None:
        _ = stitch_id
        return None

    async def list_by_tenant(self, *, tenant_id: str) -> list[Stitch]:
        _ = tenant_id
        return []

    async def list_for_event(self, *, tenant_id: str, canonical_event_type: str) -> list[Stitch]:
        _ = (tenant_id, canonical_event_type)
        return []


class FakeControlPlaneUnitOfWork(IpControlPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.connections = FakeConnectionRepository()
        self.catalogs: CatalogRepositoryPort = DummyCatalogRepo()
        self.stream_states: StreamStateRepositoryPort = DummyStreamStateRepo()
        self.sync_runs: SyncRunRepositoryPort = DummySyncRunRepo()
        self.transformations: TransformationRepositoryPort = DummyTransformationRepo()
        self.stitches: StitchRepositoryPort = DummyStitchRepo()
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
    def __init__(self) -> None:
        self.inbound_records = FakeInboundRecordRepository()
        self.outbound_records = FakeOutboundRecordRepository()
        self.replica_records: ReplicaRecordRepositoryPort = InMemoryReplicaRecordRepo()
        self.replica_rejections: ReplicaRejectionRepositoryPort = DummyReplicaRejectionRepo()
        self.normalized_records = InMemoryNormalizedRecordRepo()
        self.entity_maps: GlobalEntityMapRepositoryPort = DummyEntityMapRepo()
        self.normalization_ledger: NormalizationLedgerRepositoryPort = DummyLedgerRepo()
        self.normalization_rejections: NormalizationRejectionRepositoryPort = (
            DummyNormRejectionRepo()
        )
        self.pending_references: PendingReferenceRepositoryPort = DummyPendingRefRepo()
        self.traces: TraceRepositoryPort = InMemoryTraceRepo()
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

    async def record_idempotency(self, tenant_id: str, idempotency_key: str) -> bool:
        _ = (tenant_id, idempotency_key)
        return True

    async def release_idempotency(self, tenant_id: str, idempotency_key: str) -> None:
        _ = (tenant_id, idempotency_key)

    async def stage_outbox_envelope(self, envelope: EventEnvelope) -> None:
        _ = envelope

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


class FakeBidirectionalConnector(ConnectorPort):
    def __init__(self, app_id: str = "globex_dest") -> None:
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
            display_name="Globex Sink",
            category="ERP",
            auth_type="OAUTH2",
            description="Globex Sink API",
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
            data={"id": record_id, "quantity": 105.2},
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
            destination_id="ERP-DOC-1001",
            target_url=f"https://erp.partner.local/api/{stream_name}",
            http_method="POST",
            request_headers={
                "Authorization": f"Bearer {credentials.get('access_token', '')}",
                command.idempotency_header_name: command.idempotency_key or "",
            },
            response_status_code=201,
            response_headers={"X-Erp-Tx": "tx-88"},
            response_body={"id": "ERP-DOC-1001", "status": "POSTED"},
            duration_ms=35,
        )


def seed_oauth2_connection(
    cp_uow: FakeControlPlaneUnitOfWork,
    cipher: FakeCipher,
    *,
    tenant_id: str = "ten_alpha_1",
    app_id: str = "globex_dest",
    initial_access_tok: str = "initial_access_v1",
    initial_refresh_tok: str = "initial_refresh_v1",
    expires_offset_seconds: float = 3600.0,
) -> Connection:
    expires_epoch = datetime.now(UTC).timestamp() + expires_offset_seconds
    creds: JsonDict = {
        "client_id": "globex_client",
        "client_secret": "globex_secret",
        "token_url": "https://auth.globex.local/oauth/token",
        "access_token": initial_access_tok,
        "refresh_token": initial_refresh_tok,
        "expires_at_epoch": expires_epoch,
    }
    conn = Connection.create(
        tenant_id=tenant_id,
        app_id=app_id,
        name="Globex Production",
        auth_type=AuthType.OAUTH2,
        public_config={"base_url": "https://globex.local"},
        encrypted_credentials=cipher.encrypt(creds),
        endpoint_for_fingerprint="https://globex.local",
    )
    conn.activate()
    conn.token_expires_at = datetime.fromtimestamp(expires_epoch, tz=UTC).isoformat()
    cp_uow.connections.connections[conn.id] = conn
    return conn
