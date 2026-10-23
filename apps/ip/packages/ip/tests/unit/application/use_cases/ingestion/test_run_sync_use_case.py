"""Unit tests for RunSyncUseCase verifying L1 Data Plane and Control Plane orchestration."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from types import TracebackType

import pytest
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncCommand,
    RunSyncUseCase,
    calculate_lookback_cursor,
)
from ip.engine.domain.enums import (
    AuthType,
    ConnectionStatus,
    IngestionMode,
    SyncRunKind,
    SyncRunStatus,
)
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    PayloadNotFoundError,
    Result,
)
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.inbound_record import InboundRecord
from ip.engine.domain.models.stream_state import ConnectionStreamState
from ip.engine.domain.models.sync_run import SyncRun
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.connector_port import SourceConnectorPort
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.stream_state_repository_port import StreamStateRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
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
)
from security.ports.cipher_port import CipherPort
from seedwork.domain.types import JsonDict


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

    async def get_by_fingerprint(self, tenant_id: str, fingerprint: str) -> Connection | None:
        return None

    async def list_by_tenant(
        self, tenant_id: str, status: ConnectionStatus | None = None
    ) -> Sequence[Connection]:
        return list(self.connections.values())


class FakeStreamStateRepository(StreamStateRepositoryPort):
    def __init__(self) -> None:
        self.states: dict[tuple[str, str, str], ConnectionStreamState] = {}

    async def save(self, state: ConnectionStreamState) -> None:
        self.states[(state.tenant_id, state.connection_id, state.stream_name)] = state

    async def get_by_stream(
        self, tenant_id: str, connection_id: str, stream_name: str
    ) -> ConnectionStreamState | None:
        return self.states.get((tenant_id, connection_id, stream_name))

    async def list_by_connection(
        self, tenant_id: str, connection_id: str
    ) -> Sequence[ConnectionStreamState]:
        return [
            s
            for s in self.states.values()
            if s.tenant_id == tenant_id and s.connection_id == connection_id
        ]


class FakeSyncRunRepository(SyncRunRepositoryPort):
    def __init__(self) -> None:
        self.runs: dict[str, SyncRun] = {}

    async def save(self, run: SyncRun) -> None:
        self.runs[run.id] = run

    async def get_by_id(self, run_id: str, tenant_id: str) -> SyncRun | None:
        r = self.runs.get(run_id)
        return r if r and r.tenant_id == tenant_id else None

    async def get_active_run(
        self,
        connection_id: str,
        stream: str,
        tenant_id: str | None = None,
    ) -> SyncRun | None:
        for r in self.runs.values():
            if (
                (tenant_id is None or r.tenant_id == tenant_id)
                and r.connection_id == connection_id
                and r.stream == stream
                and r.status in (SyncRunStatus.PENDING, SyncRunStatus.RUNNING)
            ):
                return r
        return None

    async def get_latest_generation_id(
        self, tenant_id: str, connection_id: str, stream: str
    ) -> int:
        gen = 1
        for r in self.runs.values():
            if r.tenant_id == tenant_id and r.connection_id == connection_id and r.stream == stream:
                gen = max(gen, r.generation_id)
        return gen

    async def list_by_connection(
        self,
        tenant_id: str,
        connection_id: str,
        limit: int = 50,
    ) -> Sequence[SyncRun]:
        return [
            r
            for r in self.runs.values()
            if r.tenant_id == tenant_id and r.connection_id == connection_id
        ][:limit]


class FakeControlPlaneUnitOfWork(IpControlPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.connections = FakeConnectionRepository()
        self.stream_states = FakeStreamStateRepository()
        self.sync_runs = FakeSyncRunRepository()
        self.committed = False

    @property
    def catalogs(self) -> CatalogRepositoryPort:
        raise NotImplementedError

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
        self.committed = True

    async def rollback(self) -> None:
        pass


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


class FakeDataPlaneUnitOfWork(IpDataPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.inbound_records = FakeInboundRecordRepository()
        self.committed = False

    @property
    def replica_records(self) -> ReplicaRecordRepositoryPort:
        raise NotImplementedError

    @property
    def replica_rejections(self) -> ReplicaRejectionRepositoryPort:
        raise NotImplementedError

    @property
    def normalized_records(self) -> NormalizedRecordRepositoryPort:
        raise NotImplementedError

    @property
    def global_entity_map(self) -> GlobalEntityMapRepositoryPort:
        raise NotImplementedError

    @property
    def outbound_records(self) -> OutboundRecordRepositoryPort:
        raise NotImplementedError

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
        self.committed = True

    async def rollback(self) -> None:
        pass


class FakeCipher(CipherPort):
    def encrypt_str(self, text: str) -> str:
        return "enc_" + text

    def decrypt_str(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("enc_")

    def encrypt_dict(self, data: JsonDict) -> bytes:
        return b"encrypted"

    def decrypt_dict(self, encrypted_bytes: bytes) -> JsonDict:
        return {}


class FakeTieredStorageAdapter(TieredStoragePort):
    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonDict | None = None,
    ) -> TieredStorageResultDTO:
        return TieredStorageResultDTO(
            is_inlined=True,
            raw_payload=parsed_payload,
            s3_key=None,
            payload_size_bytes=len(payload_bytes),
            payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        )

    async def retrieve(self, result: TieredStorageResultDTO) -> Result[bytes, PayloadNotFoundError]:
        return Result.ok(b"")


class FakePagingConnector(SourceConnectorPort):
    def __init__(self, record_batches: list[list[JsonDict]]) -> None:
        self._record_batches = record_batches
        self.read_called_cursor: str | None = None

    @property
    def app_id(self) -> str:
        return "itron_mdm"

    def spec(self) -> AppSpecDTO:
        raise NotImplementedError

    async def check(
        self, public_config: JsonDict, credentials: JsonDict
    ) -> ConnectionCheckResultDTO:
        raise NotImplementedError

    async def discover(
        self, connection_id: str, public_config: JsonDict, credentials: JsonDict
    ) -> DiscoveredCatalogDTO:
        raise NotImplementedError

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
        self.read_called_cursor = cursor
        for batch in self._record_batches:
            for item in batch:
                yield RecordEnvelopeDTO(
                    stream_name=stream_name,
                    record_id=str(item.get("id", "")),
                    data=item,
                    emitted_at="2026-10-23T10:00:00Z",
                    cursor_value=str(item.get("timestamp")),
                )

    async def fetch_record(
        self, stream_name: str, record_id: str, public_config: JsonDict, credentials: JsonDict
    ) -> RecordEnvelopeDTO | None:
        return None


def test_calculate_lookback_cursor() -> None:
    # 5 minutes lookback on ISO string
    initial = "2026-10-23T10:05:00+00:00"
    adjusted = calculate_lookback_cursor(initial, lookback_seconds=300)
    assert adjusted == "2026-10-23T10:00:00+00:00"

    # Non-date cursor returned untouched
    assert calculate_lookback_cursor("numeric_cursor_42") == "numeric_cursor_42"
    assert calculate_lookback_cursor(None) is None


@pytest.mark.asyncio
async def test_run_sync_initial_pull() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorageAdapter()

    batch_1 = [
        {"id": "m1", "timestamp": "2026-10-23T10:00:00Z"},
        {"id": "m2", "timestamp": "2026-10-23T10:01:00Z"},
    ]
    connector = FakePagingConnector([batch_1])
    connectors = {"itron_mdm": connector}

    conn = Connection(
        id="conn_1",
        tenant_id="tenant_a",
        app_id="itron_mdm",
        name="Itron MDM Grid",
        auth_type=AuthType.API_KEY,
        connection_fingerprint="fp1",
        status=ConnectionStatus.ACTIVE,
    )
    await cp_uow.connections.save(conn)

    use_case = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors=connectors,
    )

    cmd = RunSyncCommand(
        tenant_id="tenant_a",
        connection_id="conn_1",
        stream_name="meters",
        page_batch_size=2,
    )

    res = await use_case.execute(cmd)

    assert res.status == SyncRunStatus.SUCCEEDED.value
    assert res.kind == SyncRunKind.INITIAL.value
    assert res.records_synced == 2
    assert res.end_checkpoint == "2026-10-23T10:01:00Z"

    # Check Control Plane: Stream state updated
    state = await cp_uow.stream_states.get_by_stream("tenant_a", "conn_1", "meters")
    assert state is not None
    assert state.cursor_value == "2026-10-23T10:01:00Z"
    assert state.records_synced_count == 2

    # Check Data Plane: InboundRecord persisted with PULL_INITIAL
    assert len(dp_uow.inbound_records.records) == 1
    record = next(iter(dp_uow.inbound_records.records.values()))
    assert record.ingestion_mode == IngestionMode.PULL_INITIAL
    assert record.sync_run_id == res.run_id


@pytest.mark.asyncio
async def test_run_sync_incremental_with_lookback() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorageAdapter()

    # Pre-seed existing stream state
    existing_state = ConnectionStreamState.create(
        tenant_id="tenant_a",
        connection_id="conn_1",
        stream_name="meters",
        initial_cursor="2026-10-23T10:05:00+00:00",
    )
    await cp_uow.stream_states.save(existing_state)

    connector = FakePagingConnector([])
    connectors = {"itron_mdm": connector}

    conn = Connection(
        id="conn_1",
        tenant_id="tenant_a",
        app_id="itron_mdm",
        name="Itron MDM Grid",
        auth_type=AuthType.API_KEY,
        connection_fingerprint="fp1",
        status=ConnectionStatus.ACTIVE,
    )
    await cp_uow.connections.save(conn)

    use_case = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors=connectors,
    )

    cmd = RunSyncCommand(
        tenant_id="tenant_a",
        connection_id="conn_1",
        stream_name="meters",
        lookback_seconds=300,
    )

    res = await use_case.execute(cmd)

    assert res.status == SyncRunStatus.SUCCEEDED.value
    assert res.kind == SyncRunKind.INCREMENTAL.value
    # Connector received cursor with 5 minute lookback subtracted
    assert connector.read_called_cursor == "2026-10-23T10:00:00+00:00"


@pytest.mark.asyncio
async def test_run_sync_single_active_run_enforced() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorageAdapter()

    # Seed an already active run
    existing_run = SyncRun.create(
        tenant_id="tenant_a",
        connection_id="conn_1",
        stream="meters",
        kind=SyncRunKind.INITIAL,
        generation_id=1,
    )
    existing_run.start()
    await cp_uow.sync_runs.save(existing_run)

    use_case = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors={},
    )

    cmd = RunSyncCommand(
        tenant_id="tenant_a",
        connection_id="conn_1",
        stream_name="meters",
    )

    res = await use_case.execute(cmd)

    assert res.status == "CONFLICT"
    assert res.error_code == "ACTIVE_SYNC_RUN_EXISTS"
    assert "already in state 'RUNNING'" in (res.error_message or "")


@pytest.mark.asyncio
async def test_run_sync_full_refresh_fails_when_page_cap_reached() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorageAdapter()

    # 5 pages of 10 records = 50 records
    connector = FakePagingConnector([[{"id": f"rec_{i}"}] for i in range(50)])

    conn = Connection(
        id="conn_cap_1",
        tenant_id="tenant_a",
        app_id="itron_mdm",
        name="Test Conn",
        auth_type=AuthType.NO_AUTH,
        connection_fingerprint="fp_cap",
        status=ConnectionStatus.ACTIVE,
    )
    await cp_uow.connections.save(conn)

    use_case = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors={"itron_mdm": connector},
    )

    cmd = RunSyncCommand(
        tenant_id="tenant_a",
        connection_id=conn.id,
        stream_name="meters",
        page_batch_size=10,
        max_pages=1,
        forced_kind=SyncRunKind.FULL_REFRESH,
    )

    res = await use_case.execute(cmd)

    assert res.status == SyncRunStatus.FAILED.value
    assert res.error_code == "MAX_PAGES_REACHED"
    assert "maximum page limit" in (res.error_message or "")


@pytest.mark.asyncio
async def test_run_sync_incremental_succeeds_when_page_cap_reached() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorageAdapter()

    # 5 pages of 10 records = 50 records
    connector = FakePagingConnector([[{"id": f"rec_{i}"}] for i in range(50)])

    conn = Connection(
        id="conn_cap_2",
        tenant_id="tenant_a",
        app_id="itron_mdm",
        name="Test Conn",
        auth_type=AuthType.NO_AUTH,
        connection_fingerprint="fp_cap_2",
        status=ConnectionStatus.ACTIVE,
    )
    await cp_uow.connections.save(conn)

    use_case = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors={"itron_mdm": connector},
    )

    cmd = RunSyncCommand(
        tenant_id="tenant_a",
        connection_id=conn.id,
        stream_name="meters",
        page_batch_size=10,
        max_pages=1,
        forced_kind=SyncRunKind.INCREMENTAL,
    )

    res = await use_case.execute(cmd)

    assert res.status == SyncRunStatus.SUCCEEDED.value
    assert res.pages_synced == 1
