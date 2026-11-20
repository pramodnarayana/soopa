"""Unit tests for SliceRangeStepHandler (ip.stitch.slice_range)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ip.engine.adapters.outbound.stitches.step_handlers import SliceRangeStepHandler
from ip.engine.domain.connection.connection_policy import ConnectionPolicy
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.steps import SliceRangeStepOutput
from ip.engine.ports.outbound.connection_policy_repository_port import (
    ConnectionPolicyRepositoryPort,
)
from orchestration.domain.constants import EffectPolicy, StepFailureCode
from orchestration.ports.inbound.step_handler_port import StepContext
from seedwork.domain.types import JsonDict


class InMemoryConnectionPolicyRepository(ConnectionPolicyRepositoryPort):
    """In-memory test fake implementing ConnectionPolicyRepositoryPort without mocking."""

    def __init__(self, policies: list[ConnectionPolicy] | None = None) -> None:
        self._policies: dict[tuple[str, str], ConnectionPolicy] = {
            (p.tenant_id, p.connection_id): p for p in (policies or [])
        }

    async def get_by_connection_id(
        self, tenant_id: str, connection_id: str
    ) -> ConnectionPolicy | None:
        return self._policies.get((tenant_id, connection_id))

    async def get_by_id(self, tenant_id: str, policy_id: str) -> ConnectionPolicy | None:
        for p in self._policies.values():
            if p.tenant_id == tenant_id and p.id == policy_id:
                return p
        return None

    async def save(self, policy: ConnectionPolicy) -> None:
        self._policies[(policy.tenant_id, policy.connection_id)] = policy

    async def delete(
        self,
        tenant_id: str,
        connection_id: str,
        policy: ConnectionPolicy | None = None,
    ) -> bool:
        return self._policies.pop((tenant_id, connection_id), None) is not None


@pytest.fixture
def step_context() -> StepContext:
    return StepContext(
        tenant_id="ten_ercot_utility_01",
        run_id="run_slice_1",
        step_run_id="step_slice_1",
        node_key="slice_date_range",
        retry_count=0,
        app_retry_count=0,
        internal_retry_count=0,
        trace_id="trc_slice_99",
        correlation_id="corr_telemetry_1",
        idempotency_key="idemp_slice_1",
        deadline=datetime.now(UTC),
    )


@pytest.fixture
def handler() -> SliceRangeStepHandler:
    return SliceRangeStepHandler()


def test_slice_range_step_metadata(handler: SliceRangeStepHandler) -> None:
    assert handler.step_type == StitchStepType.SLICE_RANGE.value
    assert handler.effect_policy == EffectPolicy.PURE


@pytest.mark.asyncio
async def test_slice_range_decomposes_daily_chunks(
    handler: SliceRangeStepHandler,
    step_context: StepContext,
) -> None:
    step_input: JsonDict = {
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2026-10-04T00:00:00Z",
        "target_connections": ["conn_source_north", "conn_source_south"],
        "slice_unit": "DAYS",
        "slice_size": 1,
        "filter_criteria": {
            "device_serials": ["DEV-1001", "DEV-1002"],
            "reading_type": "INTERVAL_15_MIN",
        },
        "destination": {
            "protocol": "kafka",
            "topic": "telemetry.readings.inbound",
            "partition_key": "device_serial_number",
        },
    }

    result = await handler.execute(step_context, step_input)
    assert result.is_ok
    output = SliceRangeStepOutput.from_payload(result.unwrap()).unwrap()

    # 3 days * 2 connections = 6 tasks
    assert output.total_slices == 6
    tasks = output.tasks
    assert len(tasks) == 6

    # Verify task 0 (north day 1)
    t0 = tasks[0]
    assert t0.connection_id == "conn_source_north"
    assert t0.slice_start.startswith("2026-10-01")
    assert t0.filter_criteria["device_serials"] == ["DEV-1001", "DEV-1002"]
    assert t0.destination["topic"] == "telemetry.readings.inbound"

    # Verify task 3 (south day 1)
    t3 = tasks[3]
    assert t3.connection_id == "conn_source_south"
    assert t3.slice_start.startswith("2026-10-01")


@pytest.mark.asyncio
async def test_slice_range_heterogeneous_vendor_policies(
    step_context: StepContext,
) -> None:
    """Tests heterogeneous slicing where Vendor 1 allows 1 day, Vendor 2 allows 2 days,
    and Vendor 3 allows 5 days per call for a 10-day MDM request.
    """
    tenant_id = step_context.tenant_id
    policy_v1 = ConnectionPolicy.create(
        tenant_id=tenant_id,
        connection_id="conn_vendor1_src",
        max_query_window_days=1,
        supports_wildcard_queries=True,
    )
    policy_v2 = ConnectionPolicy.create(
        tenant_id=tenant_id,
        connection_id="conn_vendor2_src",
        max_query_window_days=2,
        supports_wildcard_queries=True,
    )
    policy_v3 = ConnectionPolicy.create(
        tenant_id=tenant_id,
        connection_id="conn_vendor3_src",
        max_query_window_days=5,
        supports_wildcard_queries=True,
    )

    repo = InMemoryConnectionPolicyRepository([policy_v1, policy_v2, policy_v3])
    hetero_handler = SliceRangeStepHandler(policy_repository=repo)

    # Ingestion asks for 10 full days (2026-10-01 to 2026-10-11)
    step_input: JsonDict = {
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2026-10-11T00:00:00Z",
        "target_connections": [
            "conn_vendor1_src",
            "conn_vendor2_src",
            "conn_vendor3_src",
        ],
        "filter_criteria": {"reading_type": "INTERVAL_15_MIN"},
        "destination": {"protocol": "kafka", "topic": "telemetry.readings.inbound"},
    }

    result = await hetero_handler.execute(step_context, step_input)
    assert result.is_ok
    output = SliceRangeStepOutput.from_payload(result.unwrap()).unwrap()

    # Vendor 1: 10 days / 1 day = 10 tasks
    # Vendor 2: 10 days / 2 days = 5 tasks
    # Vendor 3: 10 days / 5 days = 2 tasks
    # Total = 17 tasks
    assert output.total_slices == 17
    tasks = output.tasks

    v1_tasks = [t for t in tasks if t.connection_id == "conn_vendor1_src"]
    v2_tasks = [t for t in tasks if t.connection_id == "conn_vendor2_src"]
    v3_tasks = [t for t in tasks if t.connection_id == "conn_vendor3_src"]

    assert len(v1_tasks) == 10
    assert len(v2_tasks) == 5
    assert len(v3_tasks) == 2


@pytest.mark.asyncio
async def test_slice_range_vendor1_upgraded_policy(
    step_context: StepContext,
) -> None:
    """Tests the scenario where Vendor 1 upgrades from 1-day capacity to 4-day capacity.
    Without altering callers or workflow code, updating Vendor 1's ConnectionPolicy immediately
    changes slicing from 10 tasks to 3 tasks.
    """
    tenant_id = step_context.tenant_id
    policy_v1 = ConnectionPolicy.create(
        tenant_id=tenant_id,
        connection_id="conn_vendor1_src",
        max_query_window_days=1,
        supports_wildcard_queries=True,
    )
    policy_v2 = ConnectionPolicy.create(
        tenant_id=tenant_id,
        connection_id="conn_vendor2_src",
        max_query_window_days=2,
        supports_wildcard_queries=True,
    )
    policy_v3 = ConnectionPolicy.create(
        tenant_id=tenant_id,
        connection_id="conn_vendor3_src",
        max_query_window_days=5,
        supports_wildcard_queries=True,
    )

    repo = InMemoryConnectionPolicyRepository([policy_v1, policy_v2, policy_v3])
    hetero_handler = SliceRangeStepHandler(policy_repository=repo)

    # 1 year later: Vendor 1 upgrades and now supports 4 days at a time!
    policy_v1.update_policy(max_query_window_days=4)
    await repo.save(policy_v1)

    step_input: JsonDict = {
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2026-10-11T00:00:00Z",
        "target_connections": [
            "conn_vendor1_src",
            "conn_vendor2_src",
            "conn_vendor3_src",
        ],
        "filter_criteria": {"reading_type": "INTERVAL_15_MIN"},
        "destination": {"protocol": "kafka", "topic": "telemetry.readings.inbound"},
    }

    result = await hetero_handler.execute(step_context, step_input)
    assert result.is_ok
    output = SliceRangeStepOutput.from_payload(result.unwrap()).unwrap()

    # Vendor 1: 10 days / 4 days = 3 tasks (Day 1-4, Day 5-8, Day 9-10)
    # Vendor 2: 10 days / 2 days = 5 tasks
    # Vendor 3: 10 days / 5 days = 2 tasks
    # Total = 10 tasks
    assert output.total_slices == 10
    tasks = output.tasks

    v1_tasks = [t for t in tasks if t.connection_id == "conn_vendor1_src"]
    assert len(v1_tasks) == 3


@pytest.mark.asyncio
async def test_slice_range_rejects_wildcard_when_unsupported(
    step_context: StepContext,
) -> None:
    tenant_id = step_context.tenant_id
    policy = ConnectionPolicy.create(
        tenant_id=tenant_id,
        connection_id="conn_strict_source",
        max_query_window_days=1,
        supports_wildcard_queries=False,  # Forbids wildcard queries
    )
    repo = InMemoryConnectionPolicyRepository([policy])
    handler = SliceRangeStepHandler(policy_repository=repo)

    step_input: JsonDict = {
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2026-10-02T00:00:00Z",
        "target_connections": ["conn_strict_source"],
        "filter_criteria": {},  # No device serials specified -> Wildcard
    }

    result = await handler.execute(step_context, step_input)
    assert result.is_err
    err = result.unwrap_err()
    assert err.code == StepFailureCode.VALIDATION_REJECTED
    assert "forbids wildcard queries" in err.detail


@pytest.mark.asyncio
async def test_slice_range_explosion_guardrail_exceeded(
    step_context: StepContext,
) -> None:
    # 600 days with 1-day slices exceeds MAX_DECOMPOSED_TASKS_PER_REQUEST (500)
    handler = SliceRangeStepHandler()
    step_input: JsonDict = {
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2025-09-01T00:00:00Z",
        "target_connections": ["conn_source_alpha"],
        "slice_size": 1,
        "slice_unit": "DAYS",
        "filter_criteria": {"device_serials": ["DEV-001"]},
    }
    result = await handler.execute(step_context, step_input)
    assert result.is_err
    err = result.unwrap_err()
    assert err.code == StepFailureCode.VALIDATION_REJECTED
    assert "exceeded maximum allowable limit" in err.detail


@pytest.mark.asyncio
async def test_slice_range_rejects_inverted_dates(
    handler: SliceRangeStepHandler,
    step_context: StepContext,
) -> None:
    step_input: JsonDict = {
        "start_date": "2026-10-10T00:00:00Z",
        "end_date": "2026-10-01T00:00:00Z",
        "target_connections": ["conn_source_alpha"],
    }
    result = await handler.execute(step_context, step_input)
    assert result.is_err
    err = result.unwrap_err()
    assert err.code == StepFailureCode.VALIDATION_REJECTED
    assert "greater than or equal to" in err.detail


@pytest.mark.asyncio
async def test_slice_range_rejects_empty_connections(
    handler: SliceRangeStepHandler,
    step_context: StepContext,
) -> None:
    step_input: JsonDict = {
        "start_date": "2026-10-01T00:00:00Z",
        "end_date": "2026-10-02T00:00:00Z",
        "target_connections": [],
    }
    result = await handler.execute(step_context, step_input)
    assert result.is_err
    err = result.unwrap_err()
    assert err.code == StepFailureCode.VALIDATION_REJECTED
    assert "at least one target connection" in err.detail
