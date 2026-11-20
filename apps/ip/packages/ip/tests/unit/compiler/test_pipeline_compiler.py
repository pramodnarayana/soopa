"""Unit tests for Universal Pipeline Compiler (Tier 2 Orchestration Layer)."""

from __future__ import annotations

import pytest
from ip.engine.application.compiler.pipeline_compiler import (
    CompilePipelineCommand,
    UniversalPipelineCompiler,
)
from ip.engine.domain.connection.connection_policy import ConnectionPolicy
from ip.engine.domain.exceptions import IpErrorCode
from ip.engine.ports.outbound.connection_policy_repository_port import (
    ConnectionPolicyRepositoryPort,
)
from ip.sdk.contracts import RequestSpec
from ip.sdk.registry import DomainFunctionRegistry
from orchestration.domain.constants import NodeKind
from seedwork.domain.types import JsonDict


class _StubConnectionPolicyRepo(ConnectionPolicyRepositoryPort):
    def __init__(self, policies: list[ConnectionPolicy] | None = None) -> None:
        self.items: dict[tuple[str, str], ConnectionPolicy] = {}
        if policies:
            for p in policies:
                self.items[(p.tenant_id, p.connection_id)] = p

    async def get_by_connection_id(
        self, tenant_id: str, connection_id: str
    ) -> ConnectionPolicy | None:
        return self.items.get((tenant_id, connection_id))

    async def save(self, policy: ConnectionPolicy) -> None:
        self.items[(policy.tenant_id, policy.connection_id)] = policy

    async def delete(self, tenant_id: str, connection_id: str) -> None:
        self.items.pop((tenant_id, connection_id), None)


def _setup_test_registry() -> DomainFunctionRegistry:
    registry = DomainFunctionRegistry()

    def dummy_connector(payload: object) -> RequestSpec:
        return RequestSpec(method="GET", path="/items")

    def dummy_transformer(raw: JsonDict) -> JsonDict:
        return {"id": "1", "status": "ACTIVE"}

    registry.register_connector("crm_app", "customers", dummy_connector)
    registry.register_transformer("crm_app", "customers", dummy_transformer)
    return registry


@pytest.mark.asyncio
async def test_compiler_synthesizes_validated_dag_pipeline() -> None:
    registry = _setup_test_registry()
    policy = ConnectionPolicy.create(
        tenant_id="tenant_alpha",
        connection_id="conn_crm_01",
        max_query_window_days=7,
        rate_limit_rpm=300,
        max_concurrency=8,
    )
    repo = _StubConnectionPolicyRepo([policy])
    compiler = UniversalPipelineCompiler(registry=registry, policy_repository=repo)

    cmd = CompilePipelineCommand(
        tenant_id="tenant_alpha",
        pipeline_id="crm_customer_pipeline",
        canonical_event_type="telemetry.customer_synced",
        source_connection_id="conn_crm_01",
        source_app="crm_app",
        source_entity="customers",
        destination_topic="core.customers.inbound",
        destination_partition_key_field="customer_id",
        description="Autonomous customer extract pipeline",
    )

    result = await compiler.compile(cmd)
    assert result.is_ok
    dto = result.unwrap()

    # Verify DAG Topology
    wf = dto.workflow_definition
    assert wf.workflow_id == "crm_customer_pipeline"
    assert len(wf.nodes) == 7

    node_keys = [n.node_key for n in wf.nodes]
    assert node_keys == [
        "slice_range",
        "http_dispatch",
        "l1_persist",
        "l2_replica",
        "normalizer",
        "ui_field_mapper",
        "egress_publish",
    ]

    # Verify root node
    roots = wf.root_nodes()
    assert len(roots) == 1
    assert roots[0].node_key == "slice_range"

    # Verify rate limit and concurrency injected from ConnectionPolicy
    http_node = wf.get_node("http_dispatch")
    assert http_node is not None
    assert http_node.rate_limit_policy is not None
    assert http_node.rate_limit_policy.capacity == 300
    assert len(http_node.concurrency_policies) == 1
    assert http_node.concurrency_policies[0].max_runs == 8

    # Verify Stitch aggregate trigger configuration
    stitch = dto.stitch
    assert stitch.id == "stch_crm_customer_pipeline"
    assert stitch.tenant_id == "tenant_alpha"
    assert stitch.canonical_event_type == "telemetry.customer_synced"
    assert stitch.idempotency_key_field == "customer_id"
    assert stitch.is_trigger is True
    assert stitch.is_active is True

    # Verify task runtime policies generated for all 7 nodes
    assert len(dto.task_configs) == 7
    config_nodes = [c.node_key for c in dto.task_configs]
    assert config_nodes == node_keys


@pytest.mark.asyncio
async def test_compiler_returns_error_when_connector_missing() -> None:
    registry = DomainFunctionRegistry()
    compiler = UniversalPipelineCompiler(registry=registry)

    cmd = CompilePipelineCommand(
        tenant_id="tenant_alpha",
        pipeline_id="missing_conn_pipe",
        canonical_event_type="telemetry.unregistered",
        source_connection_id="conn_unregistered",
        source_app="missing_app",
        source_entity="missing_entity",
        destination_topic="core.missing.inbound",
    )

    result = await compiler.compile(cmd)
    assert result.is_err
    err = result.unwrap_err()
    assert err.code == IpErrorCode.CONNECTOR_NOT_FOUND


@pytest.mark.asyncio
async def test_compiler_returns_error_when_transformer_missing() -> None:
    registry = DomainFunctionRegistry()
    registry.register_connector(
        "crm_app", "customers", lambda _: RequestSpec(method="GET", path="/")
    )
    compiler = UniversalPipelineCompiler(registry=registry)

    cmd = CompilePipelineCommand(
        tenant_id="tenant_alpha",
        pipeline_id="missing_trans_pipe",
        canonical_event_type="telemetry.unregistered",
        source_connection_id="conn_crm_01",
        source_app="crm_app",
        source_entity="customers",
        destination_topic="core.missing.inbound",
    )

    result = await compiler.compile(cmd)
    assert result.is_err
    err = result.unwrap_err()
    assert err.code == IpErrorCode.TRANSFORMER_NOT_FOUND


@pytest.mark.asyncio
async def test_compiler_honors_explicit_policy_overrides() -> None:
    registry = _setup_test_registry()
    compiler = UniversalPipelineCompiler(registry=registry)

    cmd = CompilePipelineCommand(
        tenant_id="tenant_alpha",
        pipeline_id="custom_override_pipe",
        canonical_event_type="telemetry.overridden",
        source_connection_id="conn_crm_01",
        source_app="crm_app",
        source_entity="customers",
        destination_topic="core.override.inbound",
        custom_rate_limit_rpm=600,
        custom_max_concurrency=16,
    )

    result = await compiler.compile(cmd)
    assert result.is_ok
    dto = result.unwrap()

    http_node = dto.workflow_definition.get_node("http_dispatch")
    assert http_node is not None
    assert http_node.rate_limit_policy is not None
    assert http_node.rate_limit_policy.capacity == 600
    assert len(http_node.concurrency_policies) == 1
    assert http_node.concurrency_policies[0].max_runs == 16


@pytest.mark.asyncio
async def test_compiler_synthesizes_dynamic_repeat_until_pagination() -> None:
    registry = _setup_test_registry()
    compiler = UniversalPipelineCompiler(registry=registry)

    cmd = CompilePipelineCommand(
        tenant_id="tenant_alpha",
        pipeline_id="paged_extract_pipe",
        canonical_event_type="telemetry.paged",
        source_connection_id="conn_crm_01",
        source_app="crm_app",
        source_entity="customers",
        destination_topic="core.paged.inbound",
        is_paginated=True,
        pagination_exit_predicate="is_cursor_empty",
        pagination_interval_seconds=2.5,
        custom_max_pages=250,
    )

    result = await compiler.compile(cmd)
    assert result.is_ok
    dto = result.unwrap()

    wf = dto.workflow_definition
    val_res = wf.validate()
    assert val_res.is_ok

    http_node = wf.get_node("http_dispatch")
    assert http_node is not None
    assert http_node.kind == NodeKind.REPEAT_UNTIL
    assert http_node.repeat_until is not None
    assert http_node.repeat_until.predicate_id == "is_cursor_empty"
    assert http_node.repeat_until.interval.total_seconds() == 2.5
    assert http_node.repeat_until.max_iterations == 250
