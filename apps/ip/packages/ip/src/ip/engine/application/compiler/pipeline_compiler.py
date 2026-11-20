"""Universal Platform Compiler for autonomous Synthesis of Temporal-grade DAGs from pure Solution SDK functions."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta

import structlog
from orchestration.domain.constants import (
    ConcurrencyStrategy,
    EffectPolicy,
    NodeKind,
    Priority,
)
from orchestration.domain.definition import (
    ConcurrencyPolicy,
    NodeDefinition,
    RateLimitPolicy,
    RepeatUntilSpec,
    RetryPolicy,
    WorkflowDefinition,
)

from ip.engine.domain.exceptions import (
    ConnectorNotFoundError,
    IpError,
    PipelineCompilationError,
    Result,
    TransformerNotFoundError,
)
from ip.engine.domain.stitch.enums import StitchStepType
from ip.engine.domain.stitch.stitch import Stitch
from ip.engine.domain.stitch.stitch_task_config import StitchTaskConfig
from ip.engine.ports.outbound.connection_policy_repository_port import (
    ConnectionPolicyRepositoryPort,
)
from ip.sdk.registry import DomainFunctionRegistry, default_registry

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CompilePipelineCommand:
    """Command DTO requesting autonomous synthesis of a production DAG pipeline."""

    tenant_id: str
    pipeline_id: str
    canonical_event_type: str
    source_connection_id: str
    source_app: str
    source_entity: str
    destination_topic: str
    destination_partition_key_field: str = "id"
    description: str = ""
    mapping_spec_id: str | None = None
    enable_l1_archive: bool = True
    enable_l2_replica: bool = True
    enable_declarative_mapping: bool = True
    custom_query_window_days: int | None = None
    custom_rate_limit_rpm: int | None = None
    custom_max_concurrency: int | None = None
    custom_batch_size: int | None = None
    is_paginated: bool = False
    pagination_exit_predicate: str = "is_last_page"
    pagination_interval_seconds: float = 1.0
    custom_max_pages: int = 500


@dataclass(frozen=True)
class CompiledPipelineDTO:
    """Immutable compiled artifact containing validated WorkflowDefinition, Stitch, and node configs."""

    workflow_definition: WorkflowDefinition
    stitch: Stitch
    task_configs: tuple[StitchTaskConfig, ...]
    node_keys: tuple[str, ...] = field(default_factory=tuple)


class UniversalPipelineCompiler:
    """Autonomous Universal Compiler synthesizing Temporal-grade DAG workflows from pure Solution SDK functions.

    The Solution Engineer writes zero DAG code and zero orchestration plumbing.
    The compiler automatically binds:
      1. Range Slicing with heterogeneous vendor window limits
      2. Rate-limited & circuit-broken HTTP dispatch
      3. Immutable L1 raw payload archival with SHA-256 verification
      4. Relational L2 queryable replication
      5. Pure domain normalization via Solution SDK TransformerSpec
      6. Declarative UI field mapping projection
      7. Partitioned Kafka egress publishing
    """

    def __init__(
        self,
        *,
        registry: DomainFunctionRegistry | None = None,
        policy_repository: ConnectionPolicyRepositoryPort | None = None,
    ) -> None:
        self._registry = registry or default_registry
        self._policy_repo = policy_repository

    async def compile(self, cmd: CompilePipelineCommand) -> Result[CompiledPipelineDTO, IpError]:
        bound_logger = logger.bind(
            tenant_id=cmd.tenant_id,
            pipeline_id=cmd.pipeline_id,
            source_app=cmd.source_app,
            source_entity=cmd.source_entity,
        )
        bound_logger.info("pipeline_compiler.compilation_started")

        # 1. Verify Solution Connector existence in registry
        connector_desc = self._registry.get_connector(cmd.source_app, cmd.source_entity)
        if connector_desc is None:
            bound_logger.error("pipeline_compiler.connector_not_found")
            return Result.err(
                ConnectorNotFoundError.for_app(f"{cmd.source_app}:{cmd.source_entity}")
            )

        # 2. Verify Solution Transformer existence in registry
        transformer_desc = self._registry.get_transformer(cmd.source_app, cmd.source_entity)
        if transformer_desc is None:
            bound_logger.error("pipeline_compiler.transformer_not_found")
            return Result.err(
                TransformerNotFoundError.for_version(f"{cmd.source_app}.{cmd.source_entity}", 1)
            )

        # 3. Resolve operational policy (if policy repository available)
        rate_limit_rpm = cmd.custom_rate_limit_rpm or 120
        max_concurrency = cmd.custom_max_concurrency or 5

        if self._policy_repo is not None:
            policy = await self._policy_repo.get_by_connection_id(
                tenant_id=cmd.tenant_id, connection_id=cmd.source_connection_id
            )
            if policy is not None:
                rate_limit_rpm = cmd.custom_rate_limit_rpm or policy.rate_limit_rpm
                max_concurrency = cmd.custom_max_concurrency or policy.max_concurrency

        # 4. Construct DAG Nodes
        nodes: list[NodeDefinition] = []

        # Node 1: Slicing (Root Node)
        slice_node = NodeDefinition(
            node_key="slice_range",
            kind=NodeKind.TASK,
            step_type=StitchStepType.SLICE_RANGE.value,
            parents=(),
            effect_policy=EffectPolicy.PURE,
            retry_policy=RetryPolicy(max_attempts=3, initial_backoff=timedelta(seconds=1)),
            queue_name="slicing_queue",
        )
        nodes.append(slice_node)

        # Node 2: HTTP Dispatch with Rate Limiting & Concurrency Policies
        conn_rate_limit = RateLimitPolicy(
            rate_limit_key=f"conn:{cmd.source_connection_id}",
            units=1,
            capacity=rate_limit_rpm,
            refill_per_second=max(1.0, rate_limit_rpm / 60.0),
        )
        conn_concurrency = ConcurrencyPolicy(
            strategy_id=f"conn:{cmd.source_connection_id}",
            strategy=ConcurrencyStrategy.GROUP_ROUND_ROBIN,
            max_runs=max_concurrency,
            key_template=f"conn:{cmd.source_connection_id}",
        )
        if cmd.is_paginated:
            http_node = NodeDefinition(
                node_key="http_dispatch",
                kind=NodeKind.REPEAT_UNTIL,
                step_type=StitchStepType.HTTP_DISPATCH.value,
                parents=("slice_range",),
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
                retry_policy=RetryPolicy(
                    max_attempts=5,
                    initial_backoff=timedelta(seconds=2),
                    backoff_multiplier=2.0,
                ),
                concurrency_policies=(conn_concurrency,),
                rate_limit_policy=conn_rate_limit,
                step_timeout=timedelta(minutes=15),
                queue_name="dispatch_queue",
                repeat_until=RepeatUntilSpec(
                    predicate_id=cmd.pagination_exit_predicate,
                    interval=timedelta(seconds=cmd.pagination_interval_seconds),
                    max_iterations=cmd.custom_max_pages,
                ),
            )
        else:
            http_node = NodeDefinition(
                node_key="http_dispatch",
                kind=NodeKind.TASK,
                step_type=StitchStepType.HTTP_DISPATCH.value,
                parents=("slice_range",),
                effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
                retry_policy=RetryPolicy(
                    max_attempts=5,
                    initial_backoff=timedelta(seconds=2),
                    backoff_multiplier=2.0,
                ),
                concurrency_policies=(conn_concurrency,),
                rate_limit_policy=conn_rate_limit,
                step_timeout=timedelta(minutes=3),
                queue_name="dispatch_queue",
            )
        nodes.append(http_node)

        # Node 3: L1 Immutable Raw Storage Archival
        l1_node = NodeDefinition(
            node_key="l1_persist",
            kind=NodeKind.TASK,
            step_type=StitchStepType.L1_PERSIST.value,
            parents=("http_dispatch",),
            effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            retry_policy=RetryPolicy(max_attempts=3, initial_backoff=timedelta(seconds=1)),
            queue_name="storage_queue",
        )
        nodes.append(l1_node)

        # Node 4: L2 Queryable Replica Store
        l2_node = NodeDefinition(
            node_key="l2_replica",
            kind=NodeKind.TASK,
            step_type=StitchStepType.L2_REPLICA.value,
            parents=("l1_persist",),
            effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            retry_policy=RetryPolicy(max_attempts=3, initial_backoff=timedelta(seconds=1)),
            queue_name="storage_queue",
        )
        nodes.append(l2_node)

        # Node 5: Pure Domain Normalizer (Invokes Solution SDK TransformerSpec)
        normalizer_node = NodeDefinition(
            node_key="normalizer",
            kind=NodeKind.TASK,
            step_type=StitchStepType.NORMALIZER.value,
            parents=("l2_replica",),
            effect_policy=EffectPolicy.PURE,
            retry_policy=RetryPolicy(max_attempts=1),  # Pure logic fails fast on schema corruption
            queue_name="normalize_queue",
        )
        nodes.append(normalizer_node)

        # Node 6: Declarative UI Field Mapping Projection
        ui_mapping_node = NodeDefinition(
            node_key="ui_field_mapper",
            kind=NodeKind.TASK,
            step_type=StitchStepType.UI_FIELD_MAPPER.value,
            parents=("normalizer",),
            effect_policy=EffectPolicy.PURE,
            retry_policy=RetryPolicy(max_attempts=1),
            queue_name="normalize_queue",
        )
        nodes.append(ui_mapping_node)

        # Node 7: Egress Publishing to Kafka
        egress_node = NodeDefinition(
            node_key="egress_publish",
            kind=NodeKind.TASK,
            step_type=StitchStepType.EGRESS_PUBLISH.value,
            parents=("ui_field_mapper",),
            effect_policy=EffectPolicy.IDEMPOTENT_EFFECT,
            retry_policy=RetryPolicy(
                max_attempts=5,
                initial_backoff=timedelta(seconds=1),
                backoff_multiplier=2.0,
            ),
            queue_name="egress_queue",
        )
        nodes.append(egress_node)

        # 5. Build and validate WorkflowDefinition DAG
        workflow_def = WorkflowDefinition(
            workflow_id=cmd.pipeline_id,
            version=1,
            nodes=tuple(nodes),
            default_priority=Priority.REALTIME,
            description=cmd.description
            or f"Autonomous pipeline for {cmd.source_app}.{cmd.source_entity}",
        )
        val_res = workflow_def.validate()
        if val_res.is_err:
            reason = val_res.unwrap_err().message
            bound_logger.error("pipeline_compiler.validation_failed", reason=reason)
            return Result.err(PipelineCompilationError.with_reason(cmd.pipeline_id, reason))

        # 6. Build Stitch trigger aggregate connecting canonical event to synthesized DAG
        stitch = Stitch(
            id=f"stch_{cmd.pipeline_id}",
            tenant_id=cmd.tenant_id,
            target_workflow_id=cmd.pipeline_id,
            canonical_event_type=cmd.canonical_event_type,
            name=cmd.pipeline_id,
            description=cmd.description or f"Synthesized Stitch for {cmd.source_app}",
            mapping_spec_id=cmd.mapping_spec_id,
            idempotency_key_field=cmd.destination_partition_key_field,
            is_active=True,
        )

        # 7. Build corresponding runtime StitchTaskConfigs for each node
        task_configs: list[StitchTaskConfig] = []
        for node in nodes:
            cfg = StitchTaskConfig.create(
                tenant_id=cmd.tenant_id,
                stitch_id=stitch.id,
                node_key=node.node_key,
                timeout_seconds=int(node.step_timeout.total_seconds()),
                max_attempts=node.retry_policy.max_attempts,
                initial_delay_seconds=node.retry_policy.initial_backoff.total_seconds(),
                backoff_multiplier=node.retry_policy.backoff_multiplier,
                max_delay_seconds=node.retry_policy.max_backoff.total_seconds(),
                queue_name=node.queue_name,
                max_in_flight_tasks=max_concurrency,
            )
            task_configs.append(cfg)

        node_keys = tuple(n.node_key for n in nodes)
        compiled_dto = CompiledPipelineDTO(
            workflow_definition=workflow_def,
            stitch=stitch,
            task_configs=tuple(task_configs),
            node_keys=node_keys,
        )

        bound_logger.info(
            "pipeline_compiler.compilation_succeeded",
            total_nodes=len(nodes),
            workflow_id=cmd.pipeline_id,
        )
        return Result.ok(compiled_dto)
