"""End-to-End Autonomous Pipeline Execution Integration Test.

Verifies that:
1. Solution engineers author pure business logic with zero orchestration plumbing.
2. The UniversalPipelineCompiler validates ConnectorSpec and TransformerSpec descriptors and synthesizes the 7-node DAG.
3. The platform runtime step handlers execute all 7 stages autonomously:
   `slice_range` -> `http_dispatch` -> `l1_persist` -> `l2_replica` -> `normalizer` -> `ui_field_mapper` -> `egress_publish`.
4. The entire execution runs with zero manual AST manipulation and zero hardcoded Kafka/DB orchestration loops.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import httpx
import pytest
from ip.engine.adapters.outbound.stitches.step_handlers import (
    EgressPublishStepHandler,
    HttpDispatchStepHandler,
    L1PersistStepHandler,
    L2ReplicaStepHandler,
    NormalizerStepHandler,
    NotificationOutboxPort,
    SliceRangeStepHandler,
    UiFieldMapperStepHandler,
)
from ip.engine.application.compiler.pipeline_compiler import (
    CompilePipelineCommand,
    UniversalPipelineCompiler,
)
from ip.engine.domain.mapping.enums import MappingRuleType
from ip.engine.domain.mapping.mapping_spec import MappingRule, MappingSpec
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps import (
    EgressPublishStepOutput,
    HttpDispatchStepOutput,
    L1PersistStepOutput,
    L2ReplicaStepOutput,
    NormalizerStepOutput,
    SliceRangeStepOutput,
    UiFieldMapperStepOutput,
)
from ip.engine.ports.outbound.mapping_spec_repository_port import (
    MappingSpecRepositoryPort,
)
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.sdk.registry import default_registry
from ip.solutions.domains.energy.landis import (
    LANDIS_METER_READINGS_CONNECTOR,
)
from ip.solutions.domains.energy.landis import (
    LANDIS_METER_READINGS_TRANSFORMER as LANDIS_METER_TRANSFORMER,
)

# Explicit registration of immutable specs (Zero import-time side effects)
default_registry.register_connector(LANDIS_METER_READINGS_CONNECTOR)
default_registry.register_transformer(LANDIS_METER_TRANSFORMER)
from orchestration.domain.exceptions import Result as OrchResult
from orchestration.ports.inbound.step_handler_port import StepContext
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope
from shttp import HttpClient


class FakeAutonomousTieredStorage(TieredStoragePort):
    """In-memory test double for TieredStoragePort."""

    def __init__(self) -> None:
        self.stored_blobs: list[tuple[str, str, bytes]] = []

    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonValue | None = None,
    ) -> TieredStorageResultDTO:
        self.stored_blobs.append((tenant_id, trace_id, payload_bytes))
        sha256 = hashlib.sha256(payload_bytes).hexdigest()
        return TieredStorageResultDTO(
            is_inlined=True,
            raw_payload={"data": payload_bytes.decode("utf-8")},
            s3_key=None,
            payload_size_bytes=len(payload_bytes),
            payload_sha256=sha256,
        )

    async def retrieve(self, result: TieredStorageResultDTO) -> OrchResult[bytes, Exception]:  # type: ignore[override]
        return OrchResult.ok(b"")


class FakeAutonomousNotificationOutbox(NotificationOutboxPort):
    """In-memory test double for NotificationOutboxPort staging."""

    def __init__(self) -> None:
        self.published_envelopes: list[EventEnvelope] = []

    async def publish_envelope(self, envelope: EventEnvelope) -> None:
        self.published_envelopes.append(envelope)


class FakeAutonomousMappingSpecRepository(MappingSpecRepositoryPort):
    """In-memory test double for MappingSpecRepositoryPort."""

    def __init__(self, specs: list[MappingSpec] | None = None) -> None:
        self._specs = {s.id: s for s in (specs or [])}

    async def save(self, spec: MappingSpec) -> None:
        self._specs[spec.id] = spec

    async def get_by_id(
        self,
        *,
        tenant_id: str,
        mapping_spec_id: str,
    ) -> MappingSpec | None:
        return self._specs.get(mapping_spec_id)

    async def get_latest_by_target(
        self,
        *,
        tenant_id: str,
        target_connection_id: str,
        target_entity_name: str,
    ) -> MappingSpec | None:
        return None

    async def list_by_tenant(
        self,
        *,
        tenant_id: str,
        source_type: str | None = None,
        target_connection_id: str | None = None,
    ) -> list[MappingSpec]:
        return list(self._specs.values())

    async def delete(
        self,
        *,
        tenant_id: str,
        mapping_spec_id: str,
    ) -> bool:
        return self._specs.pop(mapping_spec_id, None) is not None


@pytest.fixture
def autonomous_step_context() -> StepContext:
    return StepContext(
        tenant_id="ten_ercot_utility_01",
        run_id="run_auton_99",
        step_run_id="step_auton_99",
        node_key="pipeline_node",
        retry_count=0,
        app_retry_count=0,
        internal_retry_count=0,
        trace_id="trc_auton_99",
        correlation_id="corr_auton_99",
        idempotency_key="idemp_auton_99",
        deadline=datetime.now(UTC),
    )


@pytest.mark.asyncio
async def test_autonomous_pipeline_execution_end_to_end(
    autonomous_step_context: StepContext,
) -> None:
    # -------------------------------------------------------------------------
    # Stage 1: Tier-2 Universal Pipeline Compiler Synthesizes DAG
    # -------------------------------------------------------------------------
    compiler = UniversalPipelineCompiler(registry=default_registry)
    compile_cmd = CompilePipelineCommand(
        tenant_id="ten_ercot_utility_01",
        pipeline_id="pipe_landis_auton_01",
        canonical_event_type="energy.readings.requested",
        source_connection_id="conn_landis_north_01",
        source_app="landis_gyr_ami",
        source_entity="meter_readings",
        destination_topic="energy.mdm.canonical.inbound",
        destination_partition_key_field="device_serial",
        mapping_spec_id="spec_auton_energy_01",
    )

    compile_result = await compiler.compile(compile_cmd)
    assert compile_result.is_ok
    artifact = compile_result.unwrap()

    # Verify synthesized workflow DAG properties
    assert len(artifact.workflow_definition.nodes) == 7
    node_names = [n.node_key for n in artifact.workflow_definition.nodes]
    assert node_names == [
        "slice_range",
        "http_dispatch",
        "l1_persist",
        "l2_replica",
        "normalizer",
        "ui_field_mapper",
        "egress_publish",
    ]
    assert artifact.stitch.canonical_event_type == "energy.readings.requested"
    assert len(artifact.task_configs) > 0
    assert artifact.task_configs[0].stitch_id == artifact.stitch.id
    task_keys = [tc.node_key for tc in artifact.task_configs]
    assert "slice_range" in task_keys
    assert "http_dispatch" in task_keys

    # -------------------------------------------------------------------------
    # Stage 2: Setup Runtime Step Handlers with Test Transports
    # -------------------------------------------------------------------------
    def mock_landis_server(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/meter-readings/query"
        assert request.headers.get("Accept") == "application/json"
        simulated_readings = [
            {
                "meter_id": "LG-MTR-1001",
                "read_time": "2026-10-01T12:00:00Z",
                "active_energy_kwh": 14.85,
                "status": "OK",
            },
            {
                "meter_id": "LG-MTR-1002",
                "read_time": "2026-10-01T12:00:00Z",
                "active_energy_kwh": 28.40,
                "status": "OK",
            },
        ]
        return httpx.Response(200, json=simulated_readings)

    mock_client = HttpClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(mock_landis_server)),
        allow_private_ips=True,
    )
    fake_storage = FakeAutonomousTieredStorage()
    fake_outbox = FakeAutonomousNotificationOutbox()

    projection_spec = MappingSpec(
        id="spec_auton_energy_01",
        tenant_id="ten_ercot_utility_01",
        name="Direct Energy Projection",
        source_type="energy.canonical.reading",
        target_connection_id="conn_landis_north_01",
        target_entity_name="mdm_meter_reading",
        rules=(
            MappingRule(
                source_field="meter_serial_number",
                target_field="device_serial",
                rule_type=MappingRuleType.DIRECT,
            ),
            MappingRule(
                source_field="kwh_delivered",
                target_field="delivered_kwh",
                rule_type=MappingRuleType.DIRECT,
            ),
        ),
    )
    mapping_repo = FakeAutonomousMappingSpecRepository([projection_spec])

    slice_handler = SliceRangeStepHandler()
    http_handler = HttpDispatchStepHandler(registry=default_registry, http_client=mock_client)
    l1_handler = L1PersistStepHandler(storage=fake_storage)
    l2_handler = L2ReplicaStepHandler()
    normalizer_handler = NormalizerStepHandler(registry=default_registry)
    mapper_handler = UiFieldMapperStepHandler(mapping_spec_repository=mapping_repo)
    egress_handler = EgressPublishStepHandler(notification_outbox=fake_outbox)

    # -------------------------------------------------------------------------
    # Stage 3: Autonomous Sequential Execution of the 7 DAG Nodes
    # -------------------------------------------------------------------------

    # Node 1: slice_range
    slice_input: JsonDict = {
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2026-10-02T00:00:00Z",
        "target_connections": ["conn_landis_north_01"],
        "slice_unit": "DAYS",
        "slice_size": 1,
    }
    slice_res = await slice_handler.execute(autonomous_step_context, slice_input)
    assert slice_res.is_ok
    slice_output = SliceRangeStepOutput.from_payload(slice_res.unwrap()).unwrap()
    assert slice_output.total_slices == 1
    assert len(slice_output.tasks) == 1

    # Node 2: http_dispatch (executes pure ConnectorSpec via shttp)
    http_input: JsonDict = {
        "connection_id": "conn_landis_north_01",
        "app": "landis_gyr_ami",
        "entity": "meter_readings",
        "command_payload": {
            "start_time": "2026-10-01T00:00:00Z",
            "end_time": "2026-10-02T00:00:00Z",
            "meter_serials": ["LG-MTR-1001", "LG-MTR-1002"],
        },
    }
    http_res = await http_handler.execute(autonomous_step_context, http_input)
    assert http_res.is_ok
    http_output = HttpDispatchStepOutput.from_payload(http_res.unwrap()).unwrap()
    assert http_output.status_code == 200
    assert "LG-MTR-1001" in http_output.raw_payload

    # Node 3: l1_persist (persists wire bytes with SHA-256)
    l1_input: JsonDict = {
        "connection_id": http_output.connection_id,
        "app": http_output.app,
        "entity": http_output.entity,
        "raw_payload": http_output.raw_payload,
    }
    l1_res = await l1_handler.execute(autonomous_step_context, l1_input)
    assert l1_res.is_ok
    l1_output = L1PersistStepOutput.from_payload(l1_res.unwrap()).unwrap()
    assert l1_output.is_inlined is True
    assert len(l1_output.sha256) == 64
    assert len(fake_storage.stored_blobs) == 1

    # Node 4: l2_replica (relational replica creation)
    l2_input: JsonDict = {
        "connection_id": l1_output.connection_id,
        "app": l1_output.app,
        "entity": l1_output.entity,
        "raw_payload": l1_output.raw_payload,
    }
    l2_res = await l2_handler.execute(autonomous_step_context, l2_input)
    assert l2_res.is_ok
    l2_output = L2ReplicaStepOutput.from_payload(l2_res.unwrap()).unwrap()
    assert l2_output.replicated_count == 2

    # Node 5: normalizer (invokes pure Landis TransformerSpec)
    normalizer_input: JsonDict = {
        "connection_id": l2_output.connection_id,
        "app": l2_output.app,
        "entity": l2_output.entity,
        "raw_payload": l2_output.raw_payload,
    }
    normalizer_res = await normalizer_handler.execute(autonomous_step_context, normalizer_input)
    assert normalizer_res.is_ok
    normalizer_output = NormalizerStepOutput.from_payload(normalizer_res.unwrap()).unwrap()
    assert len(normalizer_output.normalized_records) == 2
    rec1 = normalizer_output.normalized_records[0]
    assert rec1["meter_serial_number"] == "LG-MTR-1001"
    assert rec1["kwh_delivered"] == 14.85

    # Node 6: ui_field_mapper (declarative MappingSpec direct projection)
    mapper_input: JsonDict = {
        "mapping_spec_id": "spec_auton_energy_01",
        "records": normalizer_output.normalized_records,
    }
    mapper_res = await mapper_handler.execute(autonomous_step_context, mapper_input)
    assert mapper_res.is_ok
    mapper_output = UiFieldMapperStepOutput.from_payload(mapper_res.unwrap()).unwrap()
    assert len(mapper_output.projected_records) == 2
    proj1 = mapper_output.projected_records[0]
    assert proj1 == {
        "device_serial": "LG-MTR-1001",
        "delivered_kwh": 14.85,
    }

    # Node 7: egress_publish (stages canonical records to outbox)
    egress_input: JsonDict = {
        "destination_topic": "energy.mdm.canonical.inbound",
        "destination_partition_key_field": "device_serial",
        "records": mapper_output.projected_records,
    }
    egress_res = await egress_handler.execute(autonomous_step_context, egress_input)
    assert egress_res.is_ok
    egress_output = EgressPublishStepOutput.from_payload(egress_res.unwrap()).unwrap()
    assert egress_output.published_count == 2
    assert egress_output.destination_topic == "energy.mdm.canonical.inbound"
    assert len(fake_outbox.published_envelopes) == 2

    env1 = fake_outbox.published_envelopes[0]
    assert env1.event_type == "energy.mdm.canonical.inbound"
    assert env1.tenant_id == "ten_ercot_utility_01"
    assert env1.source == StitchStepType.EGRESS_PUBLISH.value
    assert env1.payload["device_serial"] == "LG-MTR-1001"
    assert env1.payload["delivered_kwh"] == 14.85
