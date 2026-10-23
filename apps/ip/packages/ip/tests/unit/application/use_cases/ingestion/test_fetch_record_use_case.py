"""Unit tests for FetchRecordUseCase using in-memory test fakes."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from types import TracebackType

import pytest
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordCommand,
    FetchRecordUseCase,
)
from ip.engine.domain.enums import AuthType, ConnectionStatus, IngestionMode
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    PayloadNotFoundError,
    Result,
)
from ip.engine.domain.models.connection import Connection
from ip.engine.domain.models.inbound_record import InboundRecord
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


class FakeControlPlaneUnitOfWork(IpControlPlaneUnitOfWorkPort):
    def __init__(self) -> None:
        self.connections = FakeConnectionRepository()
        self.committed = False

    @property
    def catalogs(self) -> CatalogRepositoryPort:
        raise NotImplementedError

    @property
    def stream_states(self) -> StreamStateRepositoryPort:
        raise NotImplementedError

    @property
    def sync_runs(self) -> SyncRunRepositoryPort:
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
        return {"api_key": "test_key"}


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


class FakeSourceConnector(SourceConnectorPort):
    def __init__(self, records: dict[str, JsonDict]) -> None:
        self._records = records

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
        return list(self._records.keys())

    async def read_stream(
        self,
        stream_name: str,
        public_config: JsonDict,
        credentials: JsonDict,
        cursor: str | None = None,
        limit: int = 100,
    ) -> AsyncIterator[RecordEnvelopeDTO]:
        for k, v in self._records.items():
            yield RecordEnvelopeDTO(
                stream_name=stream_name,
                record_id=k,
                data=v,
                emitted_at="2026-10-23T10:00:00Z",
                cursor_value=k,
            )

    async def fetch_record(
        self, stream_name: str, record_id: str, public_config: JsonDict, credentials: JsonDict
    ) -> RecordEnvelopeDTO | None:
        if record_id in self._records:
            return RecordEnvelopeDTO(
                stream_name=stream_name,
                record_id=record_id,
                data=self._records[record_id],
                emitted_at="2026-10-23T10:00:00Z",
                cursor_value=record_id,
            )
        return None


@pytest.mark.asyncio
async def test_fetch_record_success() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorageAdapter()

    connector = FakeSourceConnector(
        records={"meter_42": {"meter_id": "meter_42", "consumption_kwh": 350.5}}
    )
    connectors = {"itron_mdm": connector}

    conn = Connection(
        id="conn_1",
        tenant_id="tenant_x",
        app_id="itron_mdm",
        name="Itron MDM Grid",
        auth_type=AuthType.API_KEY,
        connection_fingerprint="fp1",
        status=ConnectionStatus.ACTIVE,
    )
    await cp_uow.connections.save(conn)

    use_case = FetchRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors=connectors,
    )

    cmd = FetchRecordCommand(
        tenant_id="tenant_x",
        connection_id="conn_1",
        stream_name="meters",
        record_id="meter_42",
        parent_trace_id="trc_parent_notice",
    )

    result = await use_case.execute(cmd)

    assert result.status == "FETCHED"
    assert result.record_id == "meter_42"
    assert result.inbound_record_id is not None

    stored = await dp_uow.inbound_records.get_by_id(result.inbound_record_id, "tenant_x")
    assert stored is not None
    assert stored.ingestion_mode == IngestionMode.FETCH_ON_NOTIFY
    assert stored.parent_trace_id == "trc_parent_notice"
    assert stored.request_body == {"meter_id": "meter_42", "consumption_kwh": 350.5}


@pytest.mark.asyncio
async def test_fetch_record_not_found() -> None:
    cp_uow = FakeControlPlaneUnitOfWork()
    dp_uow = FakeDataPlaneUnitOfWork()
    cipher = FakeCipher()
    storage = FakeTieredStorageAdapter()

    connector = FakeSourceConnector(records={})
    connectors = {"itron_mdm": connector}

    conn = Connection(
        id="conn_1",
        tenant_id="tenant_x",
        app_id="itron_mdm",
        name="Itron MDM Grid",
        auth_type=AuthType.API_KEY,
        connection_fingerprint="fp1",
        status=ConnectionStatus.ACTIVE,
    )
    await cp_uow.connections.save(conn)

    use_case = FetchRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors=connectors,
    )

    cmd = FetchRecordCommand(
        tenant_id="tenant_x",
        connection_id="conn_1",
        stream_name="meters",
        record_id="meter_missing",
    )

    result = await use_case.execute(cmd)
    assert result.status == "NOT_FOUND"
    assert len(dp_uow.inbound_records.records) == 0
