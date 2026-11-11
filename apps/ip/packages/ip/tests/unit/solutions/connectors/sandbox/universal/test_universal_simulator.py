"""Unit tests for the Universal Schema-Driven Sandbox Simulator (inference, synthesizer, chaos, and connector)."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from types import TracebackType

import pytest
from ip.engine.adapters.outbound.inbound.ack import JsonInboundAck
from ip.engine.adapters.outbound.inbound.decoders import StandardInboundPayloadDecoder
from ip.engine.adapters.outbound.inbound.verifiers import NoOpVerifier
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType, ConnectionStatus
from ip.engine.domain.exceptions import (
    DuplicateConnectionFingerprintError,
    IpError,
    PayloadNotFoundError,
    Result,
)
from ip.engine.domain.replication.enums import IngestionMode
from ip.engine.domain.replication.inbound_record import InboundRecord
from ip.engine.ports.outbound.catalog_repository_port import CatalogRepositoryPort
from ip.engine.ports.outbound.connection_repository_port import ConnectionRepositoryPort
from ip.engine.ports.outbound.connector_port import WriteRecordCommand
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
from ip.engine.ports.outbound.stitch_repository_port import StitchRepositoryPort
from ip.engine.ports.outbound.stream_state_repository_port import StreamStateRepositoryPort
from ip.engine.ports.outbound.sync_run_repository_port import SyncRunRepositoryPort
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.engine.ports.outbound.transformation_repository_port import TransformationRepositoryPort
from ip.engine.ports.outbound.uow import (
    IpControlPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from ip.solutions.connectors.sandbox.universal import (
    JsonSchemaRecordSynthesizer,
    SimulatedPushDeliveryStyle,
    SimulatorChaosPolicy,
    SimulatorStreamSpec,
    StreamVelocityMode,
    TriggerSimulatedPushCommand,
    TriggerSimulatedPushUseCase,
    UniversalSchemaSimulatorConnector,
    extract_stream_schema_dto,
    infer_json_schema_from_sample,
    parse_simulator_manifest,
)
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope


def test_infer_json_schema_from_sample_object() -> None:
    """Infers a JSON Schema with types, formats, prefixes, and required fields from a sample JSON record."""
    sample: JsonDict = {
        "order_id": "ORD-1001",
        "customer_email": "alice@example.org",
        "total_amount": 249.95,
        "item_count": 3,
        "is_priority": True,
        "status": "APPROVED",
        "updated_at": "2026-11-10T10:00:00Z",
        "shipping_address": {
            "city": "Austin",
            "zip": "78701",
        },
        "tags": ["retail", "express"],
    }

    schema = infer_json_schema_from_sample(sample)
    assert schema["type"] == "object"
    props = schema["properties"]
    assert isinstance(props, dict)
    assert props["order_id"]["type"] == "string"
    assert props["order_id"].get("x_prefix") == "ORD-"
    assert props["customer_email"]["format"] == "email"
    assert props["total_amount"]["type"] == "number"
    assert props["item_count"]["type"] == "integer"
    assert props["is_priority"]["type"] == "boolean"
    assert props["updated_at"]["format"] == "date-time"
    assert props["shipping_address"]["type"] == "object"
    assert props["tags"]["type"] == "array"


def test_parse_simulator_manifest_from_uploaded_entities_map() -> None:
    """Parses user-created entities from public_config['streams'] supporting both raw sample JSON and JSON Schema."""
    public_config: JsonDict = {
        "seed": 99,
        "streams": {
            "orders": {
                "primary_key_field": "order_id",
                "cursor_field": "updated_at",
                "records_per_pull": 10,
                "sample_json": {
                    "order_id": "ORD-5001",
                    "amount": 120.50,
                    "status": "CREATED",
                    "updated_at": "2026-11-10T08:00:00Z",
                },
            },
            "customers": {
                "json_schema": {
                    "type": "object",
                    "required": ["customer_id", "name", "updated_at"],
                    "properties": {
                        "customer_id": {"type": "string", "pattern": "^CUST-[0-9]{4}$"},
                        "name": {"type": "string"},
                        "updated_at": {"type": "string", "format": "date-time"},
                    },
                },
                "primary_key_field": "customer_id",
                "cursor_field": "updated_at",
            },
        },
    }

    res = parse_simulator_manifest(public_config)
    assert res.is_ok
    manifest = res.unwrap()
    assert manifest.seed == 99
    assert "orders" in manifest.streams
    assert "customers" in manifest.streams

    orders_spec = manifest.streams["orders"]
    assert orders_spec.primary_key_field == "order_id"
    assert orders_spec.cursor_field == "updated_at"
    assert orders_spec.records_per_pull == 10

    dto = extract_stream_schema_dto(orders_spec)
    assert dto.name == "orders"
    assert dto.primary_key == ("order_id",)
    assert dto.cursor_field == "updated_at"
    field_names = {f.name for f in dto.fields}
    assert {"order_id", "amount", "status", "updated_at"} <= field_names


def test_synthesizer_deterministic_cursor_progression() -> None:
    """Synthesizer produces identical records for the same (seed, cursor) and strictly advances cursor timestamps."""
    schema = infer_json_schema_from_sample(
        {
            "order_id": "ORD-0001",
            "total": 99.5,
            "active": True,
            "updated_at": "2026-11-10T00:00:00Z",
        }
    )
    spec = SimulatorStreamSpec(
        stream_name="orders",
        json_schema=schema,
        primary_key_field="order_id",
        cursor_field="updated_at",
        velocity_mode=StreamVelocityMode.ENTITY_TRANSACTIONAL,
        records_per_pull=5,
        cursor_step_seconds=60,
    )

    synth = JsonSchemaRecordSynthesizer()
    batch_1a = synth.synthesize_batch(spec, seed=42, cursor="2026-11-10T12:00:00Z", limit=5)
    batch_1b = synth.synthesize_batch(spec, seed=42, cursor="2026-11-10T12:00:00Z", limit=5)

    assert len(batch_1a) == 5
    assert [r.record_id for r in batch_1a] == [r.record_id for r in batch_1b]
    assert [r.data for r in batch_1a] == [r.data for r in batch_1b]

    # Verify timestamps strictly advance beyond cursor
    last_cursor = "2026-11-10T12:00:00Z"
    for env in batch_1a:
        assert env.cursor_value is not None
        assert env.cursor_value > last_cursor
        last_cursor = env.cursor_value

    # Next pull starting from last_cursor produces newer records with distinct IDs
    batch_2 = synth.synthesize_batch(spec, seed=42, cursor=last_cursor, limit=5)
    assert len(batch_2) == 5
    assert set(r.record_id for r in batch_1a).isdisjoint(set(r.record_id for r in batch_2))
    assert batch_2[0].cursor_value is not None
    assert batch_2[0].cursor_value > last_cursor


def test_synthesizer_chaos_policy_injection() -> None:
    """Chaos policy deterministically injects duplicates and spikes when configured at 100%."""
    schema = infer_json_schema_from_sample(
        {
            "id": "ITEM-1",
            "amount": 50.0,
            "updated_at": "2026-11-10T00:00:00Z",
        }
    )
    spec = SimulatorStreamSpec(
        stream_name="items",
        json_schema=schema,
        primary_key_field="id",
        cursor_field="updated_at",
        records_per_pull=4,
        chaos_policy=SimulatorChaosPolicy(
            duplicate_rate_percent=100.0,
            spike_anomaly_rate_percent=100.0,
        ),
    )
    synth = JsonSchemaRecordSynthesizer()
    batch = synth.synthesize_batch(spec, seed=7, cursor="2026-11-10T00:00:00Z", limit=4)
    assert len(batch) == 4
    # With 100% duplicate rate on subsequent records, duplicate IDs appear in the batch
    unique_ids = {r.record_id for r in batch}
    assert len(unique_ids) < len(batch)


@pytest.mark.asyncio
async def test_universal_simulator_connector_lifecycle() -> None:
    """Verifies check, discover, read_stream, fetch_record, and write_record on UniversalSchemaSimulatorConnector."""
    connector = UniversalSchemaSimulatorConnector()
    assert connector.app_id == "universal_simulator"

    public_config: JsonDict = {
        "seed": 42,
        "streams": {
            "invoices": {
                "primary_key_field": "invoice_id",
                "cursor_field": "updated_at",
                "records_per_pull": 3,
                "sample_json": {
                    "invoice_id": "INV-100",
                    "total": 500.0,
                    "status": "ISSUED",
                    "updated_at": "2026-11-10T09:00:00Z",
                },
            }
        },
    }

    check_res = await connector.check(public_config, {})
    assert check_res.success is True
    assert check_res.status == "SUCCEEDED"

    catalog = await connector.discover("conn_sim_1", public_config, {})
    assert catalog.success is True
    assert len(catalog.streams) == 1
    assert catalog.streams[0].name == "invoices"
    assert catalog.streams[0].primary_key == ("invoice_id",)

    pulled = [
        env
        async for env in connector.read_stream(
            "invoices",
            public_config,
            {},
            cursor="2026-11-10T09:00:00Z",
            limit=3,
        )
    ]
    assert len(pulled) == 3
    assert all(env.record_id.startswith("INV-") for env in pulled)

    fetched = await connector.fetch_record("invoices", "INV-000042", public_config, {})
    assert fetched is not None
    assert fetched.record_id == "INV-000042"
    assert fetched.data["invoice_id"] == "INV-000042"

    valid_write = await connector.write_record(
        "invoices",
        WriteRecordCommand(
            stream_name="invoices",
            operation="UPSERT",
            payload={
                "invoice_id": "INV-999",
                "total": 300.0,
                "status": "PAID",
                "updated_at": "2026-11-10T10:00:00Z",
            },
            record_id="INV-999",
        ),
        public_config,
        {},
    )
    assert valid_write.success is True
    assert valid_write.response_status_code == 200

    invalid_write = await connector.write_record(
        "invoices",
        WriteRecordCommand(
            stream_name="invoices",
            operation="UPSERT",
            payload={"invoice_id": "INV-999"},  # missing required fields
            record_id="INV-999",
        ),
        public_config,
        {},
    )
    assert invalid_write.success is False
    assert invalid_write.response_status_code == 422


def test_genson_multi_sample_array_schema_merging() -> None:
    """GenSON-inspired multi-sample inference merges an array of sample objects, detecting required vs nullable and enums."""
    samples = [
        {
            "order_id": "ORD-1001",
            "status": "CREATED",
            "discount_code": "SAVE10",
            "notes": None,
            "updated_at": "2026-11-10T10:00:00Z",
        },
        {
            "order_id": "ORD-1002",
            "status": "SHIPPED",
            # discount_code omitted in sample 2 -> optional & nullable
            "notes": "Leave at front desk",
            "updated_at": "2026-11-10T10:05:00Z",
        },
    ]

    schema = infer_json_schema_from_sample(samples)
    assert schema["type"] == "object"
    required = set(schema["required"])
    assert "order_id" in required
    assert "status" in required
    assert "updated_at" in required
    assert "discount_code" not in required

    props = schema["properties"]
    assert props["discount_code"]["nullable"] is True
    assert props["notes"]["nullable"] is True
    assert props["notes"]["type"] == "string"
    assert set(props["status"]["enum"]) == {"CREATED", "SHIPPED"}


def test_jsf_semantic_field_synthesis() -> None:
    """jsf/Faker-inspired semantic field synthesis generates realistic domain values for named properties."""
    sample: JsonDict = {
        "customer_id": "CUST-0001",
        "first_name": "Alice",
        "last_name": "Morgan",
        "company_name": "Apex Logistics",
        "contact_email": "alice@example.org",
        "phone_number": "+1-555-010-9988",
        "shipping_city": "Austin",
        "currency_code": "USD",
        "item_sku": "SKU-100-A",
        "updated_at": "2026-11-10T00:00:00Z",
    }
    schema = infer_json_schema_from_sample(sample)
    spec = SimulatorStreamSpec(
        stream_name="customers",
        json_schema=schema,
        primary_key_field="customer_id",
        cursor_field="updated_at",
        records_per_pull=3,
    )
    synth = JsonSchemaRecordSynthesizer()
    batch = synth.synthesize_batch(spec, seed=101, cursor="2026-11-10T00:00:00Z", limit=3)
    assert len(batch) == 3

    rec = batch[0].data
    assert isinstance(rec["first_name"], str) and not rec["first_name"].startswith("first_name-")
    assert isinstance(rec["company_name"], str) and not rec["company_name"].startswith(
        "company_name-"
    )
    assert "@" in str(rec["contact_email"])
    assert str(rec["phone_number"]).startswith("+1-") and "-555-" in str(rec["phone_number"])
    assert str(rec["currency_code"]) in {"USD", "EUR", "GBP", "CAD", "AUD", "JPY", "INR"}
    assert str(rec["item_sku"]).startswith("SKU-")


class _FakeConnRepo(ConnectionRepositoryPort):
    def __init__(self) -> None:
        self.items: dict[str, Connection] = {}

    async def save(
        self, connection: Connection
    ) -> Result[Connection, DuplicateConnectionFingerprintError]:
        self.items[connection.id] = connection
        return Result.ok(connection)

    async def get_by_id(self, connection_id: str) -> Connection | None:
        return self.items.get(connection_id)

    async def get_by_fingerprint(self, tenant_id: str, fingerprint: str) -> Connection | None:
        _ = (tenant_id, fingerprint)
        return None

    async def list_by_tenant(
        self, tenant_id: str, status: ConnectionStatus | None = None
    ) -> list[Connection]:
        _ = status
        return [c for c in self.items.values() if c.tenant_id == tenant_id]

    async def delete(self, connection_id: str) -> bool:
        return self.items.pop(connection_id, None) is not None


class _FakeCpUoW(IpControlPlaneUnitOfWorkPort):
    connections: ConnectionRepositoryPort
    catalogs: CatalogRepositoryPort
    stream_states: StreamStateRepositoryPort
    sync_runs: SyncRunRepositoryPort
    transformations: TransformationRepositoryPort
    stitches: StitchRepositoryPort

    def __init__(self) -> None:
        self.connections = _FakeConnRepo()

    async def __aenter__(self) -> _FakeCpUoW:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def rollback(self) -> None:
        pass

    async def enqueue_outbox_event(self, event: EventEnvelope) -> None:
        _ = event


class _FakeInboundRepo(InboundRecordRepositoryPort):
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
        _ = (tenant_id, batch_id, range_start, range_end, record_ids)
        return list(self.records.values())

    async def get_by_trace_id(self, trace_id: str, tenant_id: str) -> Sequence[InboundRecord]:
        return [
            r for r in self.records.values() if r.trace_id == trace_id and r.tenant_id == tenant_id
        ]

    async def get_by_external_event_id(
        self, tenant_id: str, connection_id: str, external_event_id: str
    ) -> InboundRecord | None:
        for r in self.records.values():
            if (
                r.tenant_id == tenant_id
                and r.connection_id == connection_id
                and r.external_event_id == external_event_id
            ):
                return r
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
        _ = (tenant_id, connection_id, stream_name, limit, offset, hydrate_payloads)
        return list(self.records.values())


class _FakeDpUoW(IpDataPlaneUnitOfWorkPort):
    def __init__(self, inbound_repo: _FakeInboundRepo) -> None:
        self.inbound_records = inbound_repo
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

    async def __aenter__(self) -> _FakeDpUoW:
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


class _FakeDpUoWProvider(IpDataPlaneUnitOfWorkProviderPort):
    def __init__(self, inbound_repo: _FakeInboundRepo) -> None:
        self._inbound_repo = inbound_repo

    async def resolve_shard_info(self, tenant_id: str) -> Result[tuple[str, str], IpError]:
        _ = tenant_id
        return Result.ok(("shard_01", "mock-shard-dsn://shard_01"))

    @asynccontextmanager
    async def get_data_plane_uow(
        self,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        _ = (tenant_id, shard_id, shard_dsn)
        yield _FakeDpUoW(self._inbound_repo)


class _FakeTieredStorage(TieredStoragePort):
    async def store(
        self,
        *,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonValue | None = None,
    ) -> TieredStorageResultDTO:
        _ = (tenant_id, trace_id)
        return TieredStorageResultDTO(
            is_inlined=True,
            raw_payload=dict(parsed_payload) if isinstance(parsed_payload, dict) else None,
            s3_key=None,
            payload_size_bytes=len(payload_bytes),
            payload_sha256=hashlib.sha256(payload_bytes).hexdigest(),
        )

    async def retrieve(self, s3_key: str) -> Result[JsonValue, PayloadNotFoundError]:
        return Result.fail(PayloadNotFoundError.for_key(s3_key))


@pytest.mark.asyncio
async def test_trigger_simulated_push_use_case_delivery_modes() -> None:
    """Verifies TriggerSimulatedPushUseCase emits both FULL_PAYLOAD and THIN_PING records into L1 Ingress."""
    cp_uow = _FakeCpUoW()
    inbound_repo = _FakeInboundRepo()
    dp_provider = _FakeDpUoWProvider(inbound_repo)

    conn = Connection.create(
        tenant_id="ten_sim",
        app_id="universal_simulator",
        name="Sandbox Orders",
        auth_type=AuthType.NO_AUTH,
        encrypted_credentials=b"none",
        public_config={
            "seed": 42,
            "streams": {
                "orders": {
                    "sample_json": {
                        "order_id": "ORD-1001",
                        "total": 199.95,
                        "status": "CREATED",
                        "updated_at": "2026-11-10T10:00:00Z",
                    }
                }
            },
        },
        endpoint_for_fingerprint="sandbox://orders",
    )
    await cp_uow.connections.save(conn)

    use_case = TriggerSimulatedPushUseCase(
        control_plane_uow=cp_uow,
        data_plane_uow_provider=dp_provider,
        tiered_storage=_FakeTieredStorage(),
        verifier=NoOpVerifier(),
        decoder=StandardInboundPayloadDecoder(),
        ack=JsonInboundAck(),
    )

    # 1. FULL_PAYLOAD push
    full_res = await use_case.execute(
        TriggerSimulatedPushCommand(
            tenant_id="ten_sim",
            connection_id=conn.id,
            stream_name="orders",
            count=2,
            delivery_style=SimulatedPushDeliveryStyle.FULL_PAYLOAD,
        )
    )
    assert full_res.is_ok
    full_dto = full_res.unwrap()
    assert full_dto.records_pushed == 2
    assert len(full_dto.record_ids) == 2

    # 2. THIN_PING (Fetch-on-Notify) push
    thin_res = await use_case.execute(
        TriggerSimulatedPushCommand(
            tenant_id="ten_sim",
            connection_id=conn.id,
            stream_name="orders",
            count=1,
            delivery_style=SimulatedPushDeliveryStyle.THIN_PING,
        )
    )
    assert thin_res.is_ok
    thin_dto = thin_res.unwrap()
    assert thin_dto.records_pushed == 1
    thin_record = inbound_repo.records[thin_dto.record_ids[0]]
    assert thin_record.ingestion_mode == IngestionMode.PUSH_THIN

    # 3. Unknown entity stream fails with 404 STREAM_NOT_FOUND
    missing_stream_res = await use_case.execute(
        TriggerSimulatedPushCommand(
            tenant_id="ten_sim",
            connection_id=conn.id,
            stream_name="non_existent_stream",
            count=1,
        )
    )
    assert missing_stream_res.is_err
    assert missing_stream_res.unwrap_err().http_status == 404
