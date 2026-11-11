"""Narrow Integration Tests for L1 Ingestion Use Cases (Pull, Push, Subscribe) against real PostgreSQL."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import AsyncIterator, Sequence

import pytest
from database.types import GlobalSession, TenantSession
from ip.engine.adapters.outbound.database.models.data_plane import IpDataPlaneOutboxRecord
from ip.engine.adapters.outbound.inbound.ack import JsonInboundAck
from ip.engine.adapters.outbound.inbound.decoders import StandardInboundPayloadDecoder
from ip.engine.adapters.outbound.inbound.verifiers import HmacSignatureVerifier
from ip.engine.adapters.outbound.storage.tiered_storage_adapter import TieredStorageAdapter
from ip.engine.application.use_cases.ingestion.fetch_record_use_case import (
    FetchRecordCommand,
    FetchRecordUseCase,
)
from ip.engine.application.use_cases.ingestion.ingest_stream_batch_use_case import (
    IngestStreamBatchCommand,
    IngestStreamBatchUseCase,
)
from ip.engine.application.use_cases.ingestion.receive_push_use_case import (
    ReceivePushCommand,
    ReceivePushUseCase,
)
from ip.engine.application.use_cases.ingestion.run_sync_use_case import (
    RunSyncCommand,
    RunSyncUseCase,
)
from ip.engine.bootstrap.container import (
    create_ip_control_plane_uow,
    create_ip_data_plane_uow,
)
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType
from ip.engine.domain.dispatch.enums import AckVerdict
from ip.engine.domain.enums import IpEventType
from ip.engine.domain.exceptions import IpError, UpstreamHttpError
from ip.engine.domain.replication.enums import (
    IngestionMode,
    SyncRunKind,
    SyncRunStatus,
)
from ip.engine.ports.outbound.connector_port import (
    AppSpecDTO,
    ConnectionCheckResultDTO,
    DiscoveredCatalogDTO,
    RecordEnvelopeDTO,
    SourceConnectorPort,
)
from ip.engine.ports.outbound.subscribe_transport_port import (
    RawMessageBatchDTO,
    RawMessageDTO,
)
from security.provider import SecurityProvider
from seedwork.domain.types import JsonDict
from sqlalchemy import select

pytestmark = pytest.mark.integration


class StubPullConnector(SourceConnectorPort):
    """Real protocol-implementing source connector stub for narrow integration testing."""

    def __init__(
        self,
        records: list[JsonDict],
        stream_error: IpError | None = None,
    ) -> None:
        self._records = records
        self._last_error = stream_error
        self.received_cursor: str | None = None

    @property
    def app_id(self) -> str:
        return "acme_source"

    @property
    def last_error(self) -> IpError | None:
        return self._last_error

    def spec(self) -> AppSpecDTO:
        return AppSpecDTO(
            app_id="acme_source",
            display_name="Acme Source",
            auth_type="API_KEY",
            category="GENERIC",
        )

    async def check(
        self, public_config: JsonDict, credentials: JsonDict
    ) -> ConnectionCheckResultDTO:
        return ConnectionCheckResultDTO.ok("ok")

    async def discover(
        self,
        connection_id: str,
        public_config: JsonDict,
        credentials: JsonDict,
        *,
        tenant_id: str = "",
    ) -> DiscoveredCatalogDTO:
        return DiscoveredCatalogDTO(connection_id=connection_id)

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
        return [str(r.get("id", "")) for r in self._records]

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
        self.received_cursor = cursor
        for rec in self._records:
            yield RecordEnvelopeDTO(
                stream_name=stream_name,
                record_id=str(rec.get("id", "")),
                data=rec,
                emitted_at="2026-10-23T12:00:00Z",
                cursor_value=str(rec.get("updated_at", "")),
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
        _ = (tenant_id, connection_id)
        for rec in self._records:
            if str(rec.get("id")) == record_id:
                return RecordEnvelopeDTO(
                    stream_name=stream_name,
                    record_id=record_id,
                    data=rec,
                    emitted_at="2026-10-23T12:00:00Z",
                    cursor_value=str(rec.get("updated_at", "")),
                )
        return None


@pytest.mark.asyncio
async def test_run_sync_use_case_advances_cursor_across_runs_on_postgres(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    cp_uow = create_ip_control_plane_uow(global_session)
    dp_uow = create_ip_data_plane_uow(tenant_session)
    cipher = SecurityProvider.get_cipher()
    storage = TieredStorageAdapter()

    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="acme_source",
        name="Partner Pull Integration",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://pull.partner.example.com"},
        encrypted_credentials=cipher.encrypt({"api_key": "k1"}),
        endpoint_for_fingerprint="https://pull.partner.example.com",
    )
    async with cp_uow:
        await cp_uow.connections.save(conn)
        await cp_uow.commit()

    connector = StubPullConnector(
        records=[
            {"id": "rec_1", "updated_at": "2026-10-23T10:00:00+00:00", "quantity": 11.2},
            {"id": "rec_2", "updated_at": "2026-10-23T10:05:00+00:00", "quantity": 15.8},
        ]
    )
    use_case = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors={"acme_source": connector},
    )

    # 1. First execution -> INITIAL sync
    res1 = await use_case.execute(
        RunSyncCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream_name="records_alpha",
            page_batch_size=10,
        )
    )
    assert res1.status == SyncRunStatus.SUCCEEDED.value
    assert res1.kind == SyncRunKind.INITIAL.value
    assert res1.records_synced == 2
    assert res1.end_checkpoint == "2026-10-23T10:05:00+00:00"

    # 2. Second execution -> INCREMENTAL sync with 300s lookback
    res2 = await use_case.execute(
        RunSyncCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream_name="records_alpha",
            lookback_seconds=300,
            page_batch_size=10,
        )
    )
    assert res2.status == SyncRunStatus.SUCCEEDED.value
    assert res2.kind == SyncRunKind.INCREMENTAL.value
    assert connector.received_cursor == "2026-10-23T10:00:00+00:00"


@pytest.mark.asyncio
async def test_run_sync_use_case_marks_failed_when_connector_sets_last_error(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    cp_uow = create_ip_control_plane_uow(global_session)
    dp_uow = create_ip_data_plane_uow(tenant_session)
    cipher = SecurityProvider.get_cipher()
    storage = TieredStorageAdapter()

    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="acme_source",
        name="Partner Failing Pull",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://fail-pull.partner.example.com"},
        encrypted_credentials=cipher.encrypt({"api_key": "k1"}),
        endpoint_for_fingerprint="https://fail-pull.partner.example.com",
    )
    async with cp_uow:
        await cp_uow.connections.save(conn)
        await cp_uow.commit()

    failing_connector = StubPullConnector(
        records=[],
        stream_error=UpstreamHttpError(status_code=503, message="HTTP 503 Service Unavailable"),
    )
    use_case = RunSyncUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors={"acme_source": failing_connector},
    )

    res = await use_case.execute(
        RunSyncCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream_name="records_alpha",
        )
    )
    assert res.status == SyncRunStatus.FAILED.value
    assert res.error_code == "HTTP_ERROR"
    assert "503" in (res.error_message or "")


@pytest.mark.asyncio
async def test_thin_push_notification_hydrates_upstream_record_on_postgres(
    global_session: GlobalSession,
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    cp_uow = create_ip_control_plane_uow(global_session)
    dp_uow = create_ip_data_plane_uow(tenant_session)
    cipher = SecurityProvider.get_cipher()
    storage = TieredStorageAdapter()

    conn = Connection.create(
        tenant_id=seeded_ip_tenant,
        app_id="acme_source",
        name="Partner Push Hydration",
        auth_type=AuthType.API_KEY,
        public_config={"endpoint_url": "https://push.partner.example.com"},
        encrypted_credentials=cipher.encrypt({"api_key": "k1"}),
        endpoint_for_fingerprint="https://push.partner.example.com",
    )
    async with cp_uow:
        await cp_uow.connections.save(conn)
        await cp_uow.commit()

    secret = "whsec_partner_secret"
    raw_body = b'{"event":"record.updated","record_id":"rec_99"}'
    sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    push_uc = ReceivePushUseCase(
        uow=dp_uow,
        tiered_storage=storage,
        verifier=HmacSignatureVerifier(
            signature_header="X-Hub-Signature-256",
            timestamp_header=None,
            prefix="sha256=",
        ),
        decoder=StandardInboundPayloadDecoder(),
        ack=JsonInboundAck(status_code=202),
    )

    # 1. Valid thin push with external_event_id
    cmd = ReceivePushCommand(
        tenant_id=seeded_ip_tenant,
        connection_id=conn.id,
        app_id="acme_source",
        stream_name="records_alpha",
        raw_payload=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
        secret=secret,
        external_event_id="evt_thin_99",
        is_thin=True,
        thin_record_id="rec_99",
    )
    res1 = await push_uc.execute(cmd)
    assert res1.status_code == 202
    assert res1.is_duplicate is False
    assert res1.record_id is not None

    # Verify FetchRecordRequestedEvent was persisted to Data Plane Outbox
    outbox_stmt = select(IpDataPlaneOutboxRecord).where(
        IpDataPlaneOutboxRecord.tenant_id == seeded_ip_tenant,
        IpDataPlaneOutboxRecord.event_type == IpEventType.FETCH_RECORD_REQUESTED.value,
    )
    outbox_rows = (await tenant_session.execute(outbox_stmt)).scalars().all()
    assert len(outbox_rows) == 1

    # 2. Duplicate push with same external_event_id -> deduplicated on PostgreSQL!
    res2 = await push_uc.execute(cmd)
    assert res2.status_code == 202
    assert res2.is_duplicate is True
    assert res2.record_id == res1.record_id

    # 3. Execute FetchRecordUseCase for the thin push notification
    connector = StubPullConnector(
        records=[{"id": "rec_99", "updated_at": "2026-10-23T12:00:00Z", "quantity": 99.5}]
    )
    fetch_uc = FetchRecordUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow=dp_uow,
        tiered_storage=storage,
        cipher=cipher,
        connectors={"acme_source": connector},
    )
    fetch_res = await fetch_uc.execute(
        FetchRecordCommand(
            tenant_id=seeded_ip_tenant,
            connection_id=conn.id,
            stream_name="records_alpha",
            record_id="rec_99",
            parent_trace_id=res1.trace_id,
        )
    )
    assert fetch_res.status == "FETCHED"
    assert fetch_res.inbound_record_id is not None

    async with dp_uow:
        fetched_record = await dp_uow.inbound_records.get_by_id(
            fetch_res.inbound_record_id, seeded_ip_tenant
        )
        assert fetched_record is not None
        assert fetched_record.ingestion_mode == IngestionMode.FETCH_ON_NOTIFY
        assert fetched_record.parent_trace_id == res1.trace_id


@pytest.mark.asyncio
async def test_ingest_stream_batch_use_case_on_postgres(
    tenant_session: TenantSession,
    seeded_ip_tenant: str,
) -> None:
    dp_uow = create_ip_data_plane_uow(tenant_session)
    storage = TieredStorageAdapter()
    decoder = StandardInboundPayloadDecoder()

    stream_uc = IngestStreamBatchUseCase(
        uow=dp_uow,
        tiered_storage=storage,
        decoder=decoder,
    )

    batch = RawMessageBatchDTO(
        stream_name="interval_readings",
        messages=[
            RawMessageDTO(
                message_id="kafka-0-1001",
                raw_payload=b'{"record_id":"r1","quantity":10}',
                partition_id="0",
                broker_offset="1001",
            ),
            RawMessageDTO(
                message_id="kafka-0-1002",
                raw_payload=b'{"record_id":"r2","quantity":20}',
                partition_id="0",
                broker_offset="1002",
            ),
        ],
    )
    res1 = await stream_uc.execute(
        IngestStreamBatchCommand(
            tenant_id=seeded_ip_tenant,
            connection_id="conn_kafka_1",
            app_id="kafka",
            stream_name="interval_readings",
            batch=batch,
        )
    )
    assert res1.verdict == AckVerdict.ACK
    assert res1.records_ingested == 2
    assert res1.duplicates_skipped == 0

    # Re-delivering the same batch skips both duplicates and returns ACK
    res2 = await stream_uc.execute(
        IngestStreamBatchCommand(
            tenant_id=seeded_ip_tenant,
            connection_id="conn_kafka_1",
            app_id="kafka",
            stream_name="interval_readings",
            batch=batch,
        )
    )
    assert res2.verdict == AckVerdict.ACK
    assert res2.records_ingested == 0
    assert res2.duplicates_skipped == 2
