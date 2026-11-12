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
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import (
    AuthType,
    ConnectionStatus,
)
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    PayloadNotFoundError,
    Result,
)
from ip.engine.domain.replication.connection_entity import ConnectionEntity
from ip.engine.domain.replication.enums import (
    IngestionMode,
    SyncRunKind,
    SyncRunStatus,
)
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.domain.replication.sync_run import SyncRun
from ip.engine.ports.outbound.connection_entity_repository_port import (
    ConnectionEntityRepositoryPort,
)
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.connector_port import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    SourceConnectorPort,
)
from ip.engine.ports.outbound.entity_map_repository_port import GlobalEntityMapRepositoryPort
from ip.engine.ports.outbound.inbound_record_repository_port import InboundRecordRepositoryPort
from ip.engine.ports.outbound.normalized_record_repository_port import (
    NormalizedRecordRepositoryPort,
)
from ip.engine.ports.outbound.outbound_record_repository_port import OutboundRecordRepositoryPort
from ip.engine.ports.outbound.quarantine_record_repository_port import (
    QuarantineRecordRepositoryPort,
)
from ip.engine.ports.outbound.replica_record_repository_port import ReplicaRecordRepositoryPort
from ip.engine.ports.outbound.replica_rejection_repository_port import (
    ReplicaRejectionRepositoryPort,
)
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
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


class FakeConnectionEntityRepository(ConnectionEntityRepositoryPort):
    def __init__(self) -> None:
        self.entities: dict[tuple[str, str, str], ConnectionEntity] = {}

    async def save(self, entity: ConnectionEntity) -> None:
        self.entities[(entity.tenant_id, entity.connection_id, entity.stream_name)] = entity

    async def get_by_stream(
        self, tenant_id: str, connection_id: str, stream_name: str
    ) -> ConnectionEntity | None:
        return self.entities.get((tenant_id, connection_id, stream_name))

    async def list_by_connection(
        self, tenant_id: str, connection_id: str
    ) -> Sequence[ConnectionEntity]:
        return [
            e
            for e in self.entities.values()
            if e.tenant_id == tenant_id and e.connection_id == connection_id
        ]

    async def delete(self, entity: ConnectionEntity) -> None:
        self.entities.pop((entity.tenant_id, entity.connection_id, entity.stream_name), None)


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
        for_update: bool = False,
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
        self.entities = FakeConnectionEntityRepository()
        self.sync_runs = FakeSyncRunRepository()
        self.committed = False

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

    async def list_by_range(
        self,
        tenant_id: str,
        *,
        batch_id: str = "",
        range_start: str = "",
        range_end: str = "",
        record_ids: Sequence[str] = (),
    ) -> Sequence[InboundRecord]:
        target_ids = list(record_ids) or ([range_start] if range_start else [])
        return [
            self.records[rec_id]
            for rec_id in target_ids
            if rec_id in self.records and self.records[rec_id].tenant_id == tenant_id
        ]

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[InboundRecord]:
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

    @property
    def quarantine_records(self) -> QuarantineRecordRepositoryPort:
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
        return "acme_source"

    def spec(self) -> AppSpecDTO:
        raise NotImplementedError

    async def check(
        self, public_config: JsonDict, credentials: JsonDict
    ) -> ConnectionCheckResultDTO:
        raise NotImplementedError

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str = "",
    ) -> DiscoveredCatalogDTO:
        raise NotImplementedError

    async def list_objects(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        limit: int = 100,
        cursor: str | None = None,
        *,
        tenant_id: str = "",
        connection_id: str = "",
    ) -> Sequence[str]:
        return []

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
        *,
        tenant_id: str = "",
        connection_id: str = "",
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        _ = (tenant_id, connection_id)
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
        self,
        stream_name: str,
        record_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str = "",
        connection_id: str = "",
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
    connectors = {"acme_source": connector}

    conn = Connection(
        id="conn_1",
        tenant_id="tenant_a",
        app_id="acme_source",
        name="Acme Source Endpoint",
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
        stream_name="records_alpha",
        page_batch_size=2,
    )

    res = await use_case.execute(cmd)

    assert res.status == SyncRunStatus.SUCCEEDED.value
    assert res.kind == SyncRunKind.INITIAL.value
    assert res.records_synced == 2
    assert res.end_checkpoint == "2026-10-23T10:01:00Z"

    # Check Control Plane: Subscribed entity watermark updated
    entity = await cp_uow.entities.get_by_stream("tenant_a", "conn_1", "records_alpha")
    assert entity is not None
    assert entity.cursor_value == "2026-10-23T10:01:00Z"
    assert entity.records_synced_count == 2

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

    # Pre-seed existing subscribed entity watermark
    existing_entity = ConnectionEntity.create(
        tenant_id="tenant_a",
        connection_id="conn_1",
        stream_name="records_alpha",
        initial_cursor="2026-10-23T10:05:00+00:00",
    )
    await cp_uow.entities.save(existing_entity)

    connector = FakePagingConnector([])
    connectors = {"acme_source": connector}

    conn = Connection(
        id="conn_1",
        tenant_id="tenant_a",
        app_id="acme_source",
        name="Acme Source Endpoint",
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
        stream_name="records_alpha",
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
        stream="records_alpha",
        kind=SyncRunKind.INITIAL,
        generation_id=1,
    )
    assert existing_run.start().is_ok
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
        stream_name="records_alpha",
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
        app_id="acme_source",
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
        connectors={"acme_source": connector},
    )

    cmd = RunSyncCommand(
        tenant_id="tenant_a",
        connection_id=conn.id,
        stream_name="records_alpha",
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
        app_id="acme_source",
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
        connectors={"acme_source": connector},
    )

    cmd = RunSyncCommand(
        tenant_id="tenant_a",
        connection_id=conn.id,
        stream_name="records_alpha",
        page_batch_size=10,
        max_pages=1,
        forced_kind=SyncRunKind.INCREMENTAL,
    )

    res = await use_case.execute(cmd)

    assert res.status == SyncRunStatus.SUCCEEDED.value
    assert res.pages_synced == 1


@pytest.mark.asyncio
async def test_run_sync_full_refresh_succeeds_when_stream_ends_exactly_at_page_cap() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorageAdapter()

    # Exactly 1 page of 10 records = 10 records (stream finishes at limit without exceeding)
    connector = FakePagingConnector([[{"id": f"rec_{i}"}] for i in range(10)])

    conn = Connection(
        id="conn_cap_exact",
        tenant_id="tenant_a",
        app_id="acme_source",
        name="Test Conn",
        auth_type=AuthType.NO_AUTH,
        connection_fingerprint="fp_cap_exact",
        status=ConnectionStatus.ACTIVE,
    )
    await cp_uow.connections.save(conn)

    use_case = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors={"acme_source": connector},
    )

    cmd = RunSyncCommand(
        tenant_id="tenant_a",
        connection_id=conn.id,
        stream_name="records_alpha",
        page_batch_size=10,
        max_pages=1,
        forced_kind=SyncRunKind.FULL_REFRESH,
    )

    res = await use_case.execute(cmd)

    assert res.status == SyncRunStatus.SUCCEEDED.value
    assert res.pages_synced == 1
    assert res.records_synced == 10


def test_run_sync_use_case_requires_data_plane_dependency() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    cipher = FakeCipher()
    connector = FakePagingConnector([])

    with pytest.raises(
        ValueError, match=r"Either data_plane_uow or data_plane_uow_provider must be provided\."
    ):
        RunSyncUseCase(
            control_plane_uow=cp_uow,
            tiered_storage=storage,
            cipher=cipher,
            connectors={"acme_source": connector},
        )


@pytest.mark.asyncio
async def test_run_sync_does_not_save_when_sync_run_transition_fails() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    storage = FakeTieredStorageAdapter()
    cipher = FakeCipher()
    use_case = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors={},
    )

    terminal_run = SyncRun.create(
        tenant_id="tenant_a",
        connection_id="conn_1",
        stream="records_alpha",
        kind=SyncRunKind.INITIAL,
        generation_id=1,
    )
    assert terminal_run.start().is_ok
    assert terminal_run.succeed(end_checkpoint="c_done").is_ok

    dto = await use_case._fail_run(terminal_run, "SOME_ERR", "Should not overwrite succeeded run")
    assert dto.status == SyncRunStatus.SUCCEEDED.value
    assert dto.error_code == "INVALID_SYNC_RUN_STATE"
    assert terminal_run.id not in cp_uow.sync_runs.runs
