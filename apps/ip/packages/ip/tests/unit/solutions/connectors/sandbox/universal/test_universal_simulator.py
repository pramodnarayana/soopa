"""Unit tests for the Universal Schema Simulator under Design A (Virtual Sandboxes + API_KEY auth + UoW)."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

from helpers.delivery_fakes import (
    FakeCipher,
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
    MAX_SIMULATOR_ENTITIES_PER_SANDBOX,
    CreateSimulatorEntityCommand,
    CreateSimulatorEntityUseCase,
    CreateSimulatorSandboxCommand,
    CreateSimulatorSandboxUseCase,
    DeleteSimulatorEntityCommand,
    DeleteSimulatorEntityUseCase,
    DeleteSimulatorSandboxCommand,
    DeleteSimulatorSandboxUseCase,
    GetSimulatorSandboxQuery,
    GetSimulatorSandboxUseCase,
    ListSimulatorEntitiesQuery,
    ListSimulatorEntitiesUseCase,
    ListSimulatorSandboxesQuery,
    ListSimulatorSandboxesUseCase,
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
        return Result.ok(("ip_shard_1", "postgresql+asyncpg://localhost/ip_shard"))

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


async def test_create_sandbox_issues_prefixed_id_with_hashed_api_key_committing_uow() -> None:
    uow = FakeSimulatorUnitOfWork()
    create_uc = CreateSimulatorSandboxUseCase(uow=uow)

    res = await create_uc.execute(
        CreateSimulatorSandboxCommand(
            tenant_id="tnt_alpha",
            name="ERP Staging Sandbox",
        )
    )
    assert res.is_ok
    assert uow.commits == 1
    created = res.unwrap()
    assert created.sandbox.id.startswith("sbx_")
    assert created.api_key.startswith("sbx_key_")
    assert created.sandbox.api_key_prefix == created.api_key[:16]

    list_uc = ListSimulatorSandboxesUseCase(uow=uow)
    listed = await list_uc.execute(ListSimulatorSandboxesQuery(tenant_id="tnt_alpha"))
    assert len(listed) == 1
    assert listed[0].id == created.sandbox.id

    dup_res = await create_uc.execute(
        CreateSimulatorSandboxCommand(
            tenant_id="tnt_alpha",
            name="ERP Staging Sandbox",
        )
    )
    assert dup_res.is_err
    assert dup_res.unwrap_err().http_status == 409
    assert uow.commits == 1


async def test_sandbox_get_enforces_tenant_isolation() -> None:
    uow = FakeSimulatorUnitOfWork()
    created = (
        await CreateSimulatorSandboxUseCase(uow=uow).execute(
            CreateSimulatorSandboxCommand(tenant_id="tnt_alpha", name="Private Sandbox")
        )
    ).unwrap()

    wrong_tenant_res = await GetSimulatorSandboxUseCase(uow=uow).execute(
        GetSimulatorSandboxQuery(tenant_id="tnt_bravo", sandbox_id=created.sandbox.id)
    )
    assert wrong_tenant_res.is_err
    assert wrong_tenant_res.unwrap_err().http_status == 404

    wrong_delete_res = await DeleteSimulatorSandboxUseCase(uow=uow).execute(
        DeleteSimulatorSandboxCommand(tenant_id="tnt_bravo", sandbox_id=created.sandbox.id)
    )
    assert wrong_delete_res.is_err
    assert wrong_delete_res.unwrap_err().http_status == 404


async def test_entity_crud_lifecycle_with_timeseries_velocity_scoped_to_sandbox() -> None:
    uow = FakeSimulatorUnitOfWork()
    created_sbx = (
        await CreateSimulatorSandboxUseCase(uow=uow).execute(
            CreateSimulatorSandboxCommand(tenant_id="tnt_alpha", name="CRM Sandbox")
        )
    ).unwrap()
    sandbox_id = created_sbx.sandbox.id

    create_ent = CreateSimulatorEntityUseCase(uow=uow)
    ent_res = await create_ent.execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            sandbox_id=sandbox_id,
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
    assert entity.sandbox_id == sandbox_id
    assert entity.primary_key_field == "order_id"
    assert entity.cursor_field == "updated_at"
    assert entity.velocity_mode == StreamVelocityMode.TIMESERIES_COLUMNAR
    assert entity.version == 1

    dup_res = await create_ent.execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            sandbox_id=sandbox_id,
            entity_name="orders",
            sample_blueprint={"order_id": "ORD-1002"},
        )
    )
    assert dup_res.is_err
    assert dup_res.unwrap_err().http_status == 409

    upd_res = await UpdateSimulatorEntityUseCase(uow=uow).execute(
        UpdateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            sandbox_id=sandbox_id,
            entity_id=entity.id,
            records_per_pull=40,
            velocity_mode=StreamVelocityMode.ENTITY_TRANSACTIONAL,
        )
    )
    assert upd_res.is_ok
    assert upd_res.unwrap().version == 2
    assert upd_res.unwrap().records_per_pull == 40
    assert upd_res.unwrap().velocity_mode == StreamVelocityMode.ENTITY_TRANSACTIONAL

    listed_res = await ListSimulatorEntitiesUseCase(uow=uow).execute(
        ListSimulatorEntitiesQuery(tenant_id="tnt_alpha", sandbox_id=sandbox_id)
    )
    assert listed_res.is_ok
    assert len(listed_res.unwrap()) == 1

    del_res = await DeleteSimulatorEntityUseCase(uow=uow).execute(
        DeleteSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            sandbox_id=sandbox_id,
            entity_id=entity.id,
        )
    )
    assert del_res.is_ok


async def test_entity_quota_exceeded_returns_422() -> None:
    uow = FakeSimulatorUnitOfWork()
    created_sbx = (
        await CreateSimulatorSandboxUseCase(uow=uow).execute(
            CreateSimulatorSandboxCommand(tenant_id="tnt_alpha", name="Quota Sandbox")
        )
    ).unwrap()
    create_ent = CreateSimulatorEntityUseCase(uow=uow)

    for idx in range(MAX_SIMULATOR_ENTITIES_PER_SANDBOX):
        res = await create_ent.execute(
            CreateSimulatorEntityCommand(
                tenant_id="tnt_alpha",
                sandbox_id=created_sbx.sandbox.id,
                entity_name=f"entity_{idx:03d}",
                sample_blueprint={"id": f"REC-{idx}"},
            )
        )
        assert res.is_ok

    overflow = await create_ent.execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            sandbox_id=created_sbx.sandbox.id,
            entity_name="entity_overflow",
            sample_blueprint={"id": "REC-OVER"},
        )
    )
    assert overflow.is_err
    assert overflow.unwrap_err().http_status == 422


async def test_connector_authenticates_sandbox_api_key_for_discover_pull_fetch_write() -> None:
    repo = InMemorySimulatorRepository()
    uow = FakeSimulatorUnitOfWork(repo)
    created_sbx = (
        await CreateSimulatorSandboxUseCase(uow=uow).execute(
            CreateSimulatorSandboxCommand(tenant_id="tnt_alpha", name="Billing Sandbox")
        )
    ).unwrap()
    sandbox_id = created_sbx.sandbox.id
    api_key = created_sbx.api_key

    await CreateSimulatorEntityUseCase(uow=uow).execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            sandbox_id=sandbox_id,
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

    connector = UniversalSchemaSimulatorConnector(sandbox_reader=repo)
    spec = connector.spec()
    assert spec.auth_type == AuthType.API_KEY
    prop_map = {p.name: p for p in spec.properties}
    assert prop_map["sandbox_id"].type == PropertyType.SHORT_TEXT
    assert prop_map["sandbox_id"].required is True
    assert prop_map["api_key"].type == PropertyType.SECRET_TEXT
    assert prop_map["api_key"].required is True

    bad_check = await connector.check(
        public_config={"sandbox_id": sandbox_id},
        credentials={"api_key": "sbx_key_wrong"},
    )
    assert bad_check.success is False
    assert bad_check.error_code == IpErrorCode.INVALID_CREDENTIALS.value

    good_check = await connector.check(
        public_config={"sandbox_id": sandbox_id, "seed": 77},
        credentials={"api_key": api_key},
    )
    assert good_check.success is True

    catalog = await connector.discover(
        connection_id="conn_sim_1",
        public_config={"sandbox_id": sandbox_id, "seed": 77},
        credentials={"api_key": api_key},
    )
    assert catalog.success is True
    assert [s.name for s in catalog.streams] == ["invoices"]

    pulled = [
        rec
        async for rec in connector.read_stream(
            "invoices",
            public_config={"sandbox_id": sandbox_id, "seed": 77},
            credentials={"api_key": api_key},
            limit=3,
        )
    ]
    assert len(pulled) == 3
    assert pulled[0].record_id.startswith("INV-")

    unauthorized_pulled = [
        rec
        async for rec in connector.read_stream(
            "invoices",
            public_config={"sandbox_id": sandbox_id, "seed": 77},
            credentials={"api_key": "sbx_key_tampered"},
            limit=3,
        )
    ]
    assert len(unauthorized_pulled) == 0
    assert connector.last_error is not None
    assert connector.last_error.code == IpErrorCode.INVALID_CREDENTIALS

    fetched = await connector.fetch_record(
        "invoices",
        pulled[0].record_id,
        public_config={"sandbox_id": sandbox_id, "seed": 77},
        credentials={"api_key": api_key},
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
        public_config={"sandbox_id": sandbox_id, "seed": 77},
        credentials={"api_key": api_key},
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
        public_config={"sandbox_id": sandbox_id, "seed": 77},
        credentials={"api_key": api_key},
    )
    assert write_bad_schema.success is False
    assert write_bad_schema.failure_category == SimulatorWriteFailureCategory.SCHEMA_VIOLATION.value


async def test_simulated_push_emits_l1_records_within_single_data_plane_uow() -> None:
    repo = InMemorySimulatorRepository()
    uow = FakeSimulatorUnitOfWork(repo)
    created_sbx = (
        await CreateSimulatorSandboxUseCase(uow=uow).execute(
            CreateSimulatorSandboxCommand(tenant_id="tnt_alpha", name="Webhook Sandbox")
        )
    ).unwrap()

    await CreateSimulatorEntityUseCase(uow=uow).execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            sandbox_id=created_sbx.sandbox.id,
            entity_name="shipments",
            sample_blueprint={
                "shipment_id": "SHP-100",
                "carrier": "DHL",
                "updated_at": "2026-05-01T00:00:00Z",
            },
        )
    )

    cipher = FakeCipher()
    cp_uow = FakeControlPlaneUnitOfWork()
    conn = Connection.create(
        tenant_id="tnt_alpha",
        app_id=UniversalSchemaSimulatorConnector.APP_ID,
        name="Sandbox Connection",
        auth_type=AuthType.API_KEY,
        public_config={"sandbox_id": created_sbx.sandbox.id, "seed": 42},
        encrypted_credentials=cipher.encrypt_dict({"api_key": created_sbx.api_key}),
        endpoint_for_fingerprint=created_sbx.sandbox.id,
    )
    conn.activate()
    await cp_uow.connections.save(conn)

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
        sandbox_reader=repo,
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
    created_sbx = (
        await CreateSimulatorSandboxUseCase(uow=uow).execute(
            CreateSimulatorSandboxCommand(tenant_id="tnt_alpha", name="Chaos Retry Sandbox")
        )
    ).unwrap()
    await CreateSimulatorEntityUseCase(uow=uow).execute(
        CreateSimulatorEntityCommand(
            tenant_id="tnt_alpha",
            sandbox_id=created_sbx.sandbox.id,
            entity_name="events",
            sample_blueprint={"event_id": "EVT-1", "updated_at": "2026-05-01T00:00:00Z"},
            chaos_policy=SimulatorChaosPolicy(egress_http_error_rate_percent=50.0).to_dict(),
        )
    )
    connector = UniversalSchemaSimulatorConnector(sandbox_reader=repo)

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
            public_config={"sandbox_id": created_sbx.sandbox.id, "seed": 11},
            credentials={"api_key": created_sbx.api_key},
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
            public_config={"sandbox_id": created_sbx.sandbox.id, "seed": 11},
            credentials={"api_key": created_sbx.api_key},
        )
        anon_outcomes.add(res.success)
    assert anon_outcomes == {True, False}
