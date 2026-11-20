"""Unit tests for Tier-3 IP Stitch Step Handlers.

Tests all autonomous pipeline step handlers:
- HttpDispatchStepHandler (executes Solution SDK ConnectorSpec via platform shttp)
- L1PersistStepHandler (persists raw payload with SHA-256)
- L2ReplicaStepHandler (parses and replicas count)
- NormalizerStepHandler (invokes Solution SDK TransformerSpec)
- UiFieldMapperStepHandler (applies MappingSpec field transformations)
- EgressPublishStepHandler (stages mapped records to egress outbox)
"""

from __future__ import annotations

import hashlib
import json
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
    UiFieldMapperStepHandler,
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
    UiFieldMapperStepOutput,
)
from ip.engine.ports.outbound.mapping_spec_repository_port import (
    MappingSpecRepositoryPort,
)
from ip.engine.ports.outbound.tiered_storage_port import (
    TieredStoragePort,
    TieredStorageResultDTO,
)
from ip.sdk.contracts import RequestSpec
from ip.sdk.registry import DomainFunctionRegistry
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.domain.exceptions import Result as OrchResult
from orchestration.ports.inbound.step_handler_port import StepContext
from seedwork.domain.types import JsonDict, JsonValue
from seedwork.events import EventEnvelope
from shttp import HttpClient


class FakeTieredStorage(TieredStoragePort):
    """In-memory test double implementing TieredStoragePort."""

    def __init__(self) -> None:
        self.stored: list[tuple[str, str, bytes]] = []

    async def store(
        self,
        tenant_id: str,
        trace_id: str,
        payload_bytes: bytes,
        parsed_payload: JsonValue | None = None,
    ) -> TieredStorageResultDTO:
        self.stored.append((tenant_id, trace_id, payload_bytes))
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


class FakeMappingSpecRepository(MappingSpecRepositoryPort):
    """In-memory test double implementing MappingSpecRepositoryPort."""

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


class FakeNotificationOutbox(NotificationOutboxPort):
    """In-memory test double implementing NotificationOutboxPort."""

    def __init__(self) -> None:
        self.envelopes: list[EventEnvelope] = []

    async def publish_envelope(self, envelope: EventEnvelope) -> None:
        self.envelopes.append(envelope)


@pytest.fixture
def step_context() -> StepContext:
    return StepContext(
        tenant_id="ten_test_01",
        run_id="run_step_1",
        step_run_id="step_run_1",
        node_key="test_node",
        retry_count=0,
        app_retry_count=0,
        internal_retry_count=0,
        trace_id="trc_test_100",
        correlation_id="corr_test_100",
        idempotency_key="idemp_test_100",
        deadline=datetime.now(UTC),
    )


# ===========================================================================
# 1. HttpDispatchStepHandler Tests (shttp)
# ===========================================================================


def test_http_dispatch_metadata() -> None:
    handler = HttpDispatchStepHandler()
    assert handler.step_type == StitchStepType.HTTP_DISPATCH.value
    assert handler.effect_policy == EffectPolicy.IDEMPOTENT_EFFECT


@pytest.mark.asyncio
async def test_http_dispatch_executes_registered_connector_via_shttp(
    step_context: StepContext,
) -> None:
    registry = DomainFunctionRegistry()

    def sample_connector(cmd: JsonDict) -> RequestSpec:
        return RequestSpec(
            method="GET",
            path="/api/v1/telemetry",
            params={"device_id": str(cmd.get("device_id", ""))},
            headers={"Authorization": "Bearer test-token"},
        )

    registry.register_connector("telemetry_app", "readings", sample_connector)

    def mock_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/telemetry"
        assert request.headers.get("Authorization") == "Bearer test-token"
        return httpx.Response(
            200,
            json={"status": "SUCCESS", "readings": [{"val": 42}]},
            headers={"Content-Type": "application/json"},
        )

    mock_client = HttpClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)),
        allow_private_ips=True,
    )
    handler = HttpDispatchStepHandler(registry=registry, http_client=mock_client)

    input_payload: JsonDict = {
        "connection_id": "conn_test_01",
        "app": "telemetry_app",
        "entity": "readings",
        "command_payload": {"device_id": "DEV-999"},
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_ok
    output_res = HttpDispatchStepOutput.from_payload(result.unwrap())
    assert output_res.is_ok
    output = output_res.unwrap()
    assert output.status_code == 200
    assert "readings" in output.raw_payload


@pytest.mark.asyncio
async def test_http_dispatch_maps_upstream_4xx_to_terminal_failure(
    step_context: StepContext,
) -> None:
    registry = DomainFunctionRegistry()
    registry.register_connector(
        "telemetry_app",
        "readings",
        lambda cmd: RequestSpec(method="GET", path="/api/v1/missing"),
    )

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    mock_client = HttpClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)),
        allow_private_ips=True,
    )
    handler = HttpDispatchStepHandler(registry=registry, http_client=mock_client)

    input_payload: JsonDict = {
        "connection_id": "conn_test_01",
        "app": "telemetry_app",
        "entity": "readings",
        "command_payload": {},
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_err
    failure = result.unwrap_err()
    assert failure.code == StepFailureCode.UPSTREAM_4XX


@pytest.mark.asyncio
async def test_http_dispatch_maps_upstream_5xx_to_retryable_failure(
    step_context: StepContext,
) -> None:
    registry = DomainFunctionRegistry()
    registry.register_connector(
        "telemetry_app",
        "readings",
        lambda cmd: RequestSpec(method="GET", path="/api/v1/server_error"),
    )

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    mock_client = HttpClient(
        client=httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)),
        allow_private_ips=True,
    )
    handler = HttpDispatchStepHandler(registry=registry, http_client=mock_client)

    input_payload: JsonDict = {
        "connection_id": "conn_test_01",
        "app": "telemetry_app",
        "entity": "readings",
        "command_payload": {},
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_err
    failure = result.unwrap_err()
    assert failure.code == StepFailureCode.UPSTREAM_5XX


@pytest.mark.asyncio
async def test_http_dispatch_rejects_missing_connector(
    step_context: StepContext,
) -> None:
    empty_registry = DomainFunctionRegistry()
    handler = HttpDispatchStepHandler(registry=empty_registry)

    input_payload: JsonDict = {
        "connection_id": "conn_test_01",
        "app": "unknown_app",
        "entity": "unknown_entity",
        "command_payload": {},
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_err
    assert result.unwrap_err().code == StepFailureCode.VALIDATION_REJECTED


# ===========================================================================
# 2. L1PersistStepHandler Tests
# ===========================================================================


def test_l1_persist_metadata() -> None:
    handler = L1PersistStepHandler()
    assert handler.step_type == StitchStepType.L1_PERSIST.value
    assert handler.effect_policy == EffectPolicy.IDEMPOTENT_EFFECT


@pytest.mark.asyncio
async def test_l1_persist_stores_raw_payload_with_sha256(
    step_context: StepContext,
) -> None:
    fake_storage = FakeTieredStorage()
    handler = L1PersistStepHandler(storage=fake_storage)

    raw_data = json.dumps({"telemetry": [{"sensor": "A1", "value": 100}]})
    expected_hash = hashlib.sha256(raw_data.encode("utf-8")).hexdigest()

    input_payload: JsonDict = {
        "connection_id": "conn_test_01",
        "app": "telemetry_app",
        "entity": "readings",
        "raw_payload": raw_data,
        "content_type": "application/json",
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_ok
    output_res = L1PersistStepOutput.from_payload(result.unwrap())
    assert output_res.is_ok
    output = output_res.unwrap()
    assert output.sha256 == expected_hash
    assert len(fake_storage.stored) == 1


# ===========================================================================
# 3. L2ReplicaStepHandler Tests
# ===========================================================================


def test_l2_replica_metadata() -> None:
    handler = L2ReplicaStepHandler()
    assert handler.step_type == StitchStepType.L2_REPLICA.value
    assert handler.effect_policy == EffectPolicy.IDEMPOTENT_EFFECT


@pytest.mark.asyncio
async def test_l2_replica_parses_json_array_records(
    step_context: StepContext,
) -> None:
    handler = L2ReplicaStepHandler()

    records = [{"sensor": f"S-{i}", "val": i * 10} for i in range(5)]
    input_payload: JsonDict = {
        "connection_id": "conn_test_01",
        "app": "telemetry_app",
        "entity": "readings",
        "raw_payload": json.dumps(records),
        "sha256_digest": "dummy_digest",
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_ok
    output_res = L2ReplicaStepOutput.from_payload(result.unwrap())
    assert output_res.is_ok
    output = output_res.unwrap()
    assert output.replicated_count == 5


@pytest.mark.asyncio
async def test_l2_replica_parses_single_json_object(
    step_context: StepContext,
) -> None:
    handler = L2ReplicaStepHandler()

    record = {"sensor": "S-SINGLE", "val": 999}
    input_payload: JsonDict = {
        "connection_id": "conn_test_01",
        "app": "telemetry_app",
        "entity": "readings",
        "raw_payload": json.dumps(record),
        "sha256_digest": "dummy_digest",
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_ok
    output_res = L2ReplicaStepOutput.from_payload(result.unwrap())
    assert output_res.is_ok
    assert output_res.unwrap().replicated_count == 1


# ===========================================================================
# 4. NormalizerStepHandler Tests
# ===========================================================================


def test_normalizer_metadata() -> None:
    handler = NormalizerStepHandler()
    assert handler.step_type == StitchStepType.NORMALIZER.value
    assert handler.effect_policy == EffectPolicy.PURE


@pytest.mark.asyncio
async def test_normalizer_executes_registered_transformer(
    step_context: StepContext,
) -> None:
    registry = DomainFunctionRegistry()

    def sample_transformer(item: JsonDict) -> JsonDict:
        return {
            "canonical_id": f"can_{item['sensor']}",
            "metric_value": int(item["val"]) * 2,
        }

    registry.register_transformer("telemetry_app", "readings", sample_transformer)
    handler = NormalizerStepHandler(registry=registry)

    raw_items = [{"sensor": "A", "val": 10}, {"sensor": "B", "val": 20}]
    input_payload: JsonDict = {
        "app": "telemetry_app",
        "entity": "readings",
        "raw_payload": json.dumps(raw_items),
        "source_format": "JSON",
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_ok
    output_res = NormalizerStepOutput.from_payload(result.unwrap())
    assert output_res.is_ok
    output = output_res.unwrap()
    assert len(output.normalized_records) == 2
    assert output.normalized_records[0]["canonical_id"] == "can_A"
    assert output.normalized_records[0]["metric_value"] == 20


@pytest.mark.asyncio
async def test_normalizer_rejects_missing_transformer(
    step_context: StepContext,
) -> None:
    empty_registry = DomainFunctionRegistry()
    handler = NormalizerStepHandler(registry=empty_registry)

    input_payload: JsonDict = {
        "app": "unregistered_app",
        "entity": "readings",
        "raw_payload": "[]",
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_err
    assert result.unwrap_err().code == StepFailureCode.VALIDATION_REJECTED


# ===========================================================================
# 5. UiFieldMapperStepHandler Tests
# ===========================================================================


def test_ui_field_mapper_metadata() -> None:
    handler = UiFieldMapperStepHandler()
    assert handler.step_type == StitchStepType.UI_FIELD_MAPPER.value
    assert handler.effect_policy == EffectPolicy.PURE


@pytest.mark.asyncio
async def test_ui_field_mapper_projects_records_via_mapping_spec(
    step_context: StepContext,
) -> None:
    spec = MappingSpec(
        id="spec_test_01",
        tenant_id="ten_test_01",
        name="Telemetry Projection",
        source_type="telemetry.canonical",
        target_connection_id="conn_dest_01",
        target_entity_name="target_reading",
        rules=(
            MappingRule(
                source_field="metric_value",
                target_field="reading_kwh",
                rule_type=MappingRuleType.DIRECT,
            ),
            MappingRule(
                source_field="sensor_id",
                target_field="device_name",
                rule_type=MappingRuleType.DIRECT,
            ),
        ),
    )
    repo = FakeMappingSpecRepository([spec])
    handler = UiFieldMapperStepHandler(mapping_spec_repository=repo)

    records = [
        {"sensor_id": "SEN-001", "metric_value": 150.5, "extra": "ignore_me"},
        {"sensor_id": "SEN-002", "metric_value": 200.0, "extra": "ignore_me"},
    ]
    input_payload: JsonDict = {
        "mapping_spec_id": "spec_test_01",
        "records": records,
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_ok
    output_res = UiFieldMapperStepOutput.from_payload(result.unwrap())
    assert output_res.is_ok
    output = output_res.unwrap()
    assert len(output.projected_records) == 2
    assert output.projected_records[0] == {
        "reading_kwh": 150.5,
        "device_name": "SEN-001",
    }


# ===========================================================================
# 6. EgressPublishStepHandler Tests
# ===========================================================================


def test_egress_publish_metadata() -> None:
    handler = EgressPublishStepHandler()
    assert handler.step_type == StitchStepType.EGRESS_PUBLISH.value
    assert handler.effect_policy == EffectPolicy.IDEMPOTENT_EFFECT


@pytest.mark.asyncio
async def test_egress_publish_stages_mapped_records_to_egress(
    step_context: StepContext,
) -> None:
    fake_outbox = FakeNotificationOutbox()
    handler = EgressPublishStepHandler(notification_outbox=fake_outbox)

    records = [
        {"device_name": "SEN-001", "reading_kwh": 150.5},
        {"device_name": "SEN-002", "reading_kwh": 200.0},
    ]
    input_payload: JsonDict = {
        "records": records,
        "destination_topic": "telemetry.readings.published",
        "partition_key_field": "device_name",
    }

    result = await handler.execute(step_context, input_payload)
    assert result.is_ok
    output_res = EgressPublishStepOutput.from_payload(result.unwrap())
    assert output_res.is_ok
    output = output_res.unwrap()
    assert output.published_count == 2
    assert output.destination_topic == "telemetry.readings.published"
    assert len(fake_outbox.envelopes) == 2
    assert fake_outbox.envelopes[0].event_type == "telemetry.readings.published"
