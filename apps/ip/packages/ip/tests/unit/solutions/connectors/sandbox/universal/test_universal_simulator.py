"""Unit tests for the connection-scoped Universal Schema Simulator (`NO_AUTH`, `ip.simulator_entities`)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import pytest
from helpers.delivery_fakes import (
    FakeCipher,
    FakeConnectionRepository,
    FakeControlPlaneUnitOfWork,
    FakeDataPlaneUnitOfWork,
    FakeTieredStorage,
)
from ip.engine.adapters.outbound.inbound.ack import StandardInboundAck
from ip.engine.adapters.outbound.inbound.decoders import StandardInboundPayloadDecoder
from ip.engine.adapters.outbound.inbound.verifiers import NoOpVerifier
from ip.engine.application.use_cases.connections.token_manager_service import TokenManagerService
from ip.engine.domain.connection.connection import Connection
from ip.engine.domain.connection.enums import AuthType, PropertyType
from ip.engine.domain.exceptions import IpError, IpErrorCode, Result
from ip.engine.ports.outbound.connector_port import WriteRecordCommand
from ip.engine.ports.outbound.uow import (
    IpDataPlaneUnitOfWorkPort,
    IpDataPlaneUnitOfWorkProviderPort,
)
from ip.solutions.connectors.sandbox.universal import (
    MAX_SIMULATOR_ENTITIES_PER_CONNECTION,
    CreateSimulatorEntityCommand,
    CreateSimulatorEntityUseCase,
    DeleteSimulatorEntityCommand,
    DeleteSimulatorEntityUseCase,
    ListSimulatorEntitiesQuery,
    ListSimulatorEntitiesUseCase,
    SimulatedPushDeliveryStyle,
    SimulatorChaosPolicy,
    SimulatorStreamSpec,
    SimulatorSubmissionStatus,
    SimulatorWriteFailureCategory,
    StreamVelocityMode,
    TriggerSimulatedPushCommand,
    TriggerSimulatedPushUseCase,
    UniversalSchemaSimulatorConnector,
    UpdateSimulatorEntityCommand,
    UpdateSimulatorEntityUseCase,
    infer_json_schema_from_sample,
)
from ip.solutions.connectors.sandbox.universal.repository import (
    SqlAlchemySessionScopedSimulatorEntityReader,
)
from ip.solutions.connectors.sandbox.universal.synthesizer import (
    MAX_SYNTHESIS_ARRAY_ITEMS,
    MAX_SYNTHESIS_DIGITS,
    JsonSchemaRecordSynthesizer,
)
from unit.solutions.connectors.sandbox.universal.simulator_fakes import (
    FakeSimulatorUnitOfWork,
    InMemorySimulatorRepository,
)


class _StaticDataPlaneUoWProvider(IpDataPlaneUnitOfWorkProviderPort):
    def __init__(self, uow: IpDataPlaneUnitOfWorkPort) -> None:
        self._uow = uow
        self.checkouts = 0

    async def resolve_shard_info(self, tenant_id: str) -> Result[tuple[str, str], IpError]:
        _ = tenant_id
        return Result.ok(("ip_shard_1", "in-memory://ip-shard-1"))

    @contextlib.asynccontextmanager
    async def get_data_plane_uow(
        self,
        *,
        tenant_id: str,
        shard_id: str,
        shard_dsn: str,
    ) -> AsyncIterator[IpDataPlaneUnitOfWorkPort]:
        _ = (tenant_id, shard_id, shard_dsn)
        self.checkouts += 1
        yield self._uow


async def _seed_simulator_connection(
    connections: FakeConnectionRepository,
    *,
    tenant_id: str = "tnt_alpha",
    name: str = "Order Simulator",
    app_id: str = UniversalSchemaSimulatorConnector.APP_ID,
) -> Connection:
    conn = Connection.create(
        tenant_id=tenant_id,
        app_id=app_id,
        name=name,
        auth_type=AuthType.NO_AUTH,
        public_config={"seed": 42, "records_per_pull": 25},
        encrypted_credentials=b"",
        endpoint_for_fingerprint=name,
    )
    conn.activate()
    await connections.save(conn)
    return conn


def test_infer_schema_from_single_sample_json_detects_formats() -> None:
    sample = {
        "order_id": "ORD-00105",
        "customer_email": "alice@example.com",
        "amount": 149.95,
        "item_count": 3,
        "is_priority": True,
        "updated_at": "2026-03-01T10:00:00Z",
    }
    schema = infer_json_schema_from_sample(sample)
    assert schema["type"] == "object"
    props = schema["properties"]
    assert isinstance(props, dict)
    assert props["order_id"]["x_prefix"] == "ORD-"
    assert props["customer_email"]["format"] == "email"
    assert props["amount"]["type"] == "number"
    assert props["item_count"]["type"] == "integer"
    assert props["is_priority"]["type"] == "boolean"
    assert props["updated_at"]["format"] == "date-time"


async def test_entity_use_cases_enforce_tenant_connection_ownership() -> None:
    uow = FakeSimulatorUnitOfWork()
    connections = FakeConnectionRepository()
    alpha_conn = await _seed_simulator_connection(connections, tenant_id="tnt_alpha")
    non_sim_conn = await _seed_simulator_connection(
        connections,
        tenant_id="tnt_alpha",
        name="QuickBooks Prod",
        app_id="quickbooks",
    )

    wrong_tenant_res = await ListSimulatorEntitiesUseCase(uow=uow, connections=connections).execute(
        ListSimulatorEntitiesQuery(tenant_id="tnt_bravo", connection_id=alpha_conn.id)
    )
    assert wrong_tenant_res.is_err
    assert wrong_tenant_res.unwrap_err().http_status == 404

    wrong_app_res = await CreateSimulatorEntityUseCase(uow=uow, connections=connections).execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            connection_id=non_sim_conn.id,
            entity_name="orders",
            sample_blueprint={"order_id": "ORD-1001"},
        )
    )
    assert wrong_app_res.is_err
    assert wrong_app_res.unwrap_err().http_status == 400


async def test_entity_crud_lifecycle_scoped_to_connection() -> None:
    uow = FakeSimulatorUnitOfWork()
    connections = FakeConnectionRepository()
    conn = await _seed_simulator_connection(connections, tenant_id="tnt_alpha")

    create_ent = CreateSimulatorEntityUseCase(uow=uow, connections=connections)
    ent_res = await create_ent.execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            connection_id=conn.id,
            entity_name="orders",
            sample_blueprint={
                "order_id": "ORD-1001",
                "total": 250.0,
                "updated_at": "2026-04-01T00:00:00Z",
            },
            records_per_pull=10,
            velocity_mode=StreamVelocityMode.TIMESERIES_COLUMNAR,
        )
    )
    assert ent_res.is_ok
    entity = ent_res.unwrap()
    assert entity.id.startswith("sim_ent_")
    assert entity.connection_id == conn.id
    assert entity.primary_key_field == "order_id"
    assert entity.cursor_field == "updated_at"
    assert entity.velocity_mode == StreamVelocityMode.TIMESERIES_COLUMNAR
    assert entity.version == 1

    dup_res = await create_ent.execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            connection_id=conn.id,
            entity_name="orders",
            sample_blueprint={"order_id": "ORD-1002"},
        )
    )
    assert dup_res.is_err
    assert dup_res.unwrap_err().http_status == 409

    upd_res = await UpdateSimulatorEntityUseCase(uow=uow, connections=connections).execute(
        UpdateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            connection_id=conn.id,
            entity_id=entity.id,
            records_per_pull=40,
            velocity_mode=StreamVelocityMode.ENTITY_TRANSACTIONAL,
        )
    )
    assert upd_res.is_ok
    assert upd_res.unwrap().version == 2
    assert upd_res.unwrap().records_per_pull == 40
    assert upd_res.unwrap().velocity_mode == StreamVelocityMode.ENTITY_TRANSACTIONAL

    listed_res = await ListSimulatorEntitiesUseCase(uow=uow, connections=connections).execute(
        ListSimulatorEntitiesQuery(tenant_id="tnt_alpha", connection_id=conn.id)
    )
    assert listed_res.is_ok
    assert len(listed_res.unwrap()) == 1

    del_res = await DeleteSimulatorEntityUseCase(uow=uow, connections=connections).execute(
        DeleteSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            connection_id=conn.id,
            entity_id=entity.id,
        )
    )
    assert del_res.is_ok


async def test_entity_quota_exceeded_returns_422() -> None:
    uow = FakeSimulatorUnitOfWork()
    connections = FakeConnectionRepository()
    conn = await _seed_simulator_connection(connections, tenant_id="tnt_alpha")
    create_ent = CreateSimulatorEntityUseCase(uow=uow, connections=connections)

    for idx in range(MAX_SIMULATOR_ENTITIES_PER_CONNECTION):
        res = await create_ent.execute(
            CreateSimulatorEntityCommand(
                tenant_id="tnt_alpha",
                connection_id=conn.id,
                entity_name=f"entity_{idx:03d}",
                sample_blueprint={"id": f"REC-{idx}"},
            )
        )
        assert res.is_ok

    overflow = await create_ent.execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            connection_id=conn.id,
            entity_name="entity_overflow",
            sample_blueprint={"id": "REC-OVER"},
        )
    )
    assert overflow.is_err
    assert overflow.unwrap_err().http_status == 422


async def test_connector_executes_no_auth_discover_pull_fetch_write_with_typed_scope() -> None:
    repo = InMemorySimulatorRepository()
    uow = FakeSimulatorUnitOfWork(repo)
    connections = FakeConnectionRepository()
    conn = await _seed_simulator_connection(connections, tenant_id="tnt_alpha")

    await CreateSimulatorEntityUseCase(uow=uow, connections=connections).execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            connection_id=conn.id,
            entity_name="invoices",
            sample_blueprint={
                "invoice_id": "INV-0001",
                "total": 99.5,
                "updated_at": "2026-05-01T00:00:00Z",
            },
            records_per_pull=5,
            chaos_policy=SimulatorChaosPolicy(egress_http_error_rate_percent=0.0).to_dict(),
        )
    )

    connector = UniversalSchemaSimulatorConnector(entity_reader=repo)
    spec = connector.spec()
    assert spec.auth_type == AuthType.NO_AUTH
    prop_map = {p.name: p for p in spec.properties}
    assert set(prop_map.keys()) == {"seed", "records_per_pull"}
    assert prop_map["seed"].type == PropertyType.NUMBER
    assert prop_map["seed"].required is False

    good_check = await connector.check(
        public_config={"seed": 77, "records_per_pull": 25},
        credentials={},
    )
    assert good_check.success is True

    catalog = await connector.discover(
        connection_id=conn.id,
        public_config={"seed": 77},
        credentials={},
        tenant_id="tnt_alpha",
    )
    assert catalog.success is True
    assert [s.name for s in catalog.streams] == ["invoices"]

    pulled = [
        rec
        async for rec in connector.read_stream(
            "invoices",
            public_config={"seed": 77},
            credentials={},
            limit=3,
            tenant_id="tnt_alpha",
            connection_id=conn.id,
        )
    ]
    assert len(pulled) == 3
    assert pulled[0].record_id.startswith("INV-")

    missing_scope_pulled = [
        rec
        async for rec in connector.read_stream(
            "invoices",
            public_config={"seed": 77},
            credentials={},
            limit=3,
            tenant_id="",
            connection_id="",
        )
    ]
    assert len(missing_scope_pulled) == 0
    assert connector.last_error is not None
    assert connector.last_error.code == IpErrorCode.INVALID_CONFIG

    fetched = await connector.fetch_record(
        "invoices",
        pulled[0].record_id,
        public_config={"seed": 77},
        credentials={},
        tenant_id="tnt_alpha",
        connection_id=conn.id,
    )
    assert fetched is not None
    assert fetched == pulled[0]

    write_ok = await connector.write_record(
        "invoices",
        WriteRecordCommand(
            stream_name="invoices",
            operation="UPSERT",
            payload={
                "invoice_id": "INV-9001",
                "total": 120.0,
                "updated_at": "2026-05-02T00:00:00Z",
            },
            record_id="INV-9001",
        ),
        public_config={"seed": 77},
        credentials={},
        tenant_id="tnt_alpha",
        connection_id=conn.id,
    )
    assert write_ok.success is True
    assert write_ok.response_status_code == 200
    assert write_ok.response_body is not None
    assert write_ok.response_body["status"] == SimulatorSubmissionStatus.ACCEPTED.value

    write_bad_schema = await connector.write_record(
        "invoices",
        WriteRecordCommand(
            stream_name="invoices",
            operation="UPSERT",
            payload={"invoice_id": "INV-9002", "total": "not_a_number"},
            record_id="INV-9002",
        ),
        public_config={"seed": 77},
        credentials={},
        tenant_id="tnt_alpha",
        connection_id=conn.id,
    )
    assert write_bad_schema.success is False
    assert write_bad_schema.failure_category == SimulatorWriteFailureCategory.SCHEMA_VIOLATION.value


async def test_simulated_push_emits_l1_records_within_single_data_plane_uow() -> None:
    repo = InMemorySimulatorRepository()
    uow = FakeSimulatorUnitOfWork(repo)
    cipher = FakeCipher()
    cp_uow = FakeControlPlaneUnitOfWork()

    conn = Connection.create(
        tenant_id="tnt_alpha",
        app_id=UniversalSchemaSimulatorConnector.APP_ID,
        name="Simulator Connection",
        auth_type=AuthType.NO_AUTH,
        public_config={"seed": 42},
        encrypted_credentials=b"",
        endpoint_for_fingerprint="Simulator Connection",
    )
    conn.activate()
    await cp_uow.connections.save(conn)

    await CreateSimulatorEntityUseCase(uow=uow, connections=cp_uow.connections).execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            connection_id=conn.id,
            entity_name="shipments",
            sample_blueprint={
                "shipment_id": "SHP-100",
                "carrier": "DHL",
                "updated_at": "2026-05-01T00:00:00Z",
            },
        )
    )

    dp_uow = FakeDataPlaneUnitOfWork()
    dp_provider = _StaticDataPlaneUoWProvider(dp_uow)
    storage = FakeTieredStorage()
    token_manager = TokenManagerService(control_plane_uow=cp_uow, cipher=cipher)

    push_uc = TriggerSimulatedPushUseCase(
        data_plane_uow_provider=dp_provider,
        tiered_storage=storage,
        verifier=NoOpVerifier(),
        decoder=StandardInboundPayloadDecoder(),
        ack=StandardInboundAck(),
        token_manager=token_manager,
        entity_reader=repo,
    )
    res = await push_uc.execute(
        TriggerSimulatedPushCommand(
            tenant_id="tnt_alpha",
            connection_id=conn.id,
            stream_name="shipments",
            count=3,
            delivery_style=SimulatedPushDeliveryStyle.FULL_PAYLOAD,
        )
    )
    assert res.is_ok
    pushed = res.unwrap()
    assert pushed.records_pushed == 3
    assert len(pushed.record_ids) == 3
    assert dp_provider.checkouts == 1


def test_synthesizer_bounds_tenant_schema_digit_widths_with_array_caps() -> None:
    synthesizer = JsonSchemaRecordSynthesizer()
    spec = SimulatorStreamSpec(
        stream_name="orders",
        primary_key_field="order_id",
        cursor_field="updated_at",
        json_schema={
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "string",
                    "x_prefix": "ORD-",
                    "x_digits": 5_000_000,
                },
                "tracking_code": {
                    "type": "string",
                    "pattern": r"^TRK-\d{999999}$",
                },
                "line_items": {
                    "type": "array",
                    "minItems": 50_000,
                    "maxItems": 90_000,
                    "items": {"type": "string"},
                },
                "updated_at": {"type": "string", "format": "date-time"},
            },
        },
        records_per_pull=2,
    )

    batch = synthesizer.synthesize_batch(spec, seed=19, limit=1)
    assert len(batch) == 1
    rec = batch[0]
    assert len(rec.record_id) == len("ORD-") + MAX_SYNTHESIS_DIGITS
    tracking_val = rec.data["tracking_code"]
    assert isinstance(tracking_val, str)
    assert len(tracking_val) == len("TRK-") + MAX_SYNTHESIS_DIGITS
    items_val = rec.data["line_items"]
    assert isinstance(items_val, list)
    assert len(items_val) == MAX_SYNTHESIS_ARRAY_ITEMS

    fetched = synthesizer.synthesize_record_by_id(spec, seed=19, record_id=rec.record_id)
    assert fetched == rec


async def test_connector_write_chaos_varies_across_retry_attempts() -> None:
    repo = InMemorySimulatorRepository()
    uow = FakeSimulatorUnitOfWork(repo)
    connections = FakeConnectionRepository()
    conn = await _seed_simulator_connection(connections, tenant_id="tnt_alpha")

    await CreateSimulatorEntityUseCase(uow=uow, connections=connections).execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            connection_id=conn.id,
            entity_name="events",
            sample_blueprint={"event_id": "EVT-1", "updated_at": "2026-05-01T00:00:00Z"},
            chaos_policy=SimulatorChaosPolicy(egress_http_error_rate_percent=50.0).to_dict(),
        )
    )
    connector = UniversalSchemaSimulatorConnector(entity_reader=repo)

    attempt_outcomes: set[bool] = set()
    for attempt in range(1, 12):
        res = await connector.write_record(
            "events",
            WriteRecordCommand(
                stream_name="events",
                operation="CREATE",
                payload={"event_id": "EVT-RETRY", "updated_at": "2026-05-01T00:00:00Z"},
                attempt_number=attempt,
            ),
            public_config={"seed": 11},
            credentials={},
            tenant_id="tnt_alpha",
            connection_id=conn.id,
        )
        attempt_outcomes.add(res.success)
    assert attempt_outcomes == {True, False}

    anon_outcomes: set[bool] = set()
    for idx in range(16):
        res = await connector.write_record(
            "events",
            WriteRecordCommand(
                stream_name="events",
                operation="CREATE",
                payload={"event_id": f"EVT-ANON-{idx}", "updated_at": "2026-05-01T00:00:00Z"},
            ),
            public_config={"seed": 11},
            credentials={},
            tenant_id="tnt_alpha",
            connection_id=conn.id,
        )
        anon_outcomes.add(res.success)
    assert anon_outcomes == {True, False}


async def test_connector_discover_returns_empty_streams_when_zero_entities_exist() -> None:
    repo = InMemorySimulatorRepository()
    connector = UniversalSchemaSimulatorConnector(entity_reader=repo)

    catalog = await connector.discover(
        connection_id="conn_empty_sim",
        public_config={"seed": 42, "records_per_pull": 25},
        credentials={},
        tenant_id="tnt_alpha",
    )

    assert catalog.success is True
    assert catalog.error is None
    assert tuple(catalog.streams) == ()


async def test_connector_discover_returns_error_when_runtime_scope_is_invalid() -> None:
    unbound_connector = UniversalSchemaSimulatorConnector(entity_reader=None)
    no_reader_catalog = await unbound_connector.discover(
        connection_id="conn_sim_1",
        public_config={"seed": 42},
        credentials={},
        tenant_id="tnt_alpha",
    )
    assert no_reader_catalog.success is False
    assert no_reader_catalog.error is not None
    assert no_reader_catalog.error.code == IpErrorCode.INVALID_CONFIG

    repo = InMemorySimulatorRepository()
    connector = UniversalSchemaSimulatorConnector(entity_reader=repo)
    missing_tenant_catalog = await connector.discover(
        connection_id="conn_sim_1",
        public_config={"seed": 42},
        credentials={},
        tenant_id="",
    )
    assert missing_tenant_catalog.success is False
    assert missing_tenant_catalog.error is not None
    assert missing_tenant_catalog.error.code == IpErrorCode.INVALID_CONFIG


async def test_session_scoped_reader_raises_runtime_error_without_database_binding() -> None:
    reader = SqlAlchemySessionScopedSimulatorEntityReader()

    with pytest.raises(RuntimeError, match="no bound DatabaseRouterPort or DatabaseProvider"):
        await reader.list_entities_by_connection("tnt_alpha", "conn_sim_1")

    with pytest.raises(RuntimeError, match="no bound DatabaseRouterPort or DatabaseProvider"):
        await reader.get_entity_by_name("tnt_alpha", "conn_sim_1", "orders")


async def test_simulated_push_rejects_non_simulator_connection_with_400() -> None:
    repo = InMemorySimulatorRepository()
    cipher = FakeCipher()
    cp_uow = FakeControlPlaneUnitOfWork()
    non_sim_conn = Connection.create(
        tenant_id="tnt_alpha",
        app_id="quickbooks",
        name="QuickBooks Prod",
        auth_type=AuthType.NO_AUTH,
        public_config={},
        encrypted_credentials=b"",
        endpoint_for_fingerprint="QuickBooks Prod",
    )
    non_sim_conn.activate()
    await cp_uow.connections.save(non_sim_conn)

    push_uc = TriggerSimulatedPushUseCase(
        data_plane_uow_provider=_StaticDataPlaneUoWProvider(FakeDataPlaneUnitOfWork()),
        tiered_storage=FakeTieredStorage(),
        verifier=NoOpVerifier(),
        decoder=StandardInboundPayloadDecoder(),
        ack=StandardInboundAck(),
        token_manager=TokenManagerService(control_plane_uow=cp_uow, cipher=cipher),
        entity_reader=repo,
    )
    res = await push_uc.execute(
        TriggerSimulatedPushCommand(
            tenant_id="tnt_alpha",
            connection_id=non_sim_conn.id,
            stream_name="orders",
            count=2,
        )
    )
    assert res.is_err
    err = res.unwrap_err()
    assert err.code == IpErrorCode.INVALID_CONFIG
    assert err.http_status == 400
