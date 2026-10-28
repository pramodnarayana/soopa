"""Control Plane and inspection use cases for Layer-4 Stitch definitions, stitches, and runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import structlog
from orchestration.domain.definition import NodeDefinition, WorkflowDefinition
from orchestration.domain.run import StepRun, WorkflowRun
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort
from seedwork.domain.types import JsonDict
from seedwork.id_registry import DomainIdPrefix, SystemIdPrefix
from seedwork.utils import generate_id

from ip.engine.application.use_cases.stitch.dispatch_canonical_event_to_stitches_use_case import (
    DispatchCanonicalEventResultDTO,
)
from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.exceptions import (
    InvalidConnectionConfigError,
    IpError,
    IpErrorCode,
    Result,
    StitchDefinitionNotFoundError,
)
from ip.engine.domain.stitch import Stitch
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
    StitchShardGatewayPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StitchNodeSummaryDTO:
    """Pure boundary DTO representing a static node in a Stitch WorkflowDefinition."""

    node_key: str
    kind: str
    step_type: str
    parents: tuple[str, ...]
    edge_condition: str
    effect_policy: str
    wait_event_key: str | None
    queue_name: str


@dataclass(frozen=True)
class StitchDefinitionSummaryDTO:
    """Pure boundary DTO representing a registered Stitch WorkflowDefinition DAG."""

    workflow_id: str
    version: int
    default_priority: str
    description: str
    nodes: tuple[StitchNodeSummaryDTO, ...]


@dataclass(frozen=True)
class StitchSummaryDTO:
    """Pure boundary DTO representing a Stitch."""

    id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    canonical_event_type: str
    is_trigger: bool
    condition_event_key: str | None
    idempotency_key_field: str
    concurrency_key_field: str | None
    resource_hint_field: str | None
    is_active: bool


@dataclass(frozen=True)
class StitchStepRunSummaryDTO:
    """Pure boundary DTO representing a StepRun inside a WorkflowRun."""

    step_run_id: str
    node_key: str
    status: str
    retry_count: int
    app_retry_count: int
    internal_retry_count: int
    iteration_count: int
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime
    finished_at: datetime | None


@dataclass(frozen=True)
class StitchRunSummaryDTO:
    """Pure boundary DTO representing a durable Stitch WorkflowRun and its steps."""

    run_id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    status: str
    priority: str
    concurrency_key: str | None
    idempotency_key: str
    trace_id: str
    correlation_id: str | None
    failure_code: str | None
    failure_detail: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    steps: tuple[StitchStepRunSummaryDTO, ...]


@dataclass(frozen=True)
class GetStitchDefinitionQuery:
    """Query to fetch a specific Stitch WorkflowDefinition by ID and optional version."""

    workflow_id: str
    version: int | None = None


@dataclass(frozen=True)
class ListStitchesQuery:
    """Query to list all Stitches active or registered for a tenant."""

    tenant_id: str


@dataclass(frozen=True)
class RegisterStitchCommand:
    """Command to register or update a Stitch for a tenant."""

    tenant_id: str
    workflow_id: str
    workflow_version: int
    canonical_event_type: str
    stitch_id: str | None = None
    is_trigger: bool = True
    condition_event_key: str | None = None
    idempotency_key_field: str = "id"
    concurrency_key_field: str | None = None
    resource_hint_field: str | None = None
    is_active: bool = True


@dataclass(frozen=True)
class TriggerStitchEventCommand:
    """Command to dispatch a canonical event to matching Stitches on the tenant shard."""

    tenant_id: str
    canonical_event_type: str
    payload: JsonDict
    event_id: str | None = None
    trace_id: str | None = None
    correlation_id: str | None = None


@dataclass(frozen=True)
class GetStitchRunQuery:
    """Query to inspect a Stitch WorkflowRun on a tenant shard."""

    tenant_id: str
    run_id: str


def _to_node_dto(node: NodeDefinition) -> StitchNodeSummaryDTO:
    return StitchNodeSummaryDTO(
        node_key=node.node_key,
        kind=node.kind.value,
        step_type=node.step_type,
        parents=node.parents,
        edge_condition=node.edge_condition.value,
        effect_policy=node.effect_policy.value,
        wait_event_key=node.wait_event.event_key if node.wait_event is not None else None,
        queue_name=node.queue_name,
    )


def _to_definition_dto(defn: WorkflowDefinition) -> StitchDefinitionSummaryDTO:
    return StitchDefinitionSummaryDTO(
        workflow_id=defn.workflow_id,
        version=defn.version,
        default_priority=defn.default_priority.name,
        description=defn.description,
        nodes=tuple(_to_node_dto(n) for n in defn.nodes),
    )


def _to_stitch_dto(stitch: Stitch) -> StitchSummaryDTO:
    return StitchSummaryDTO(
        id=stitch.id,
        tenant_id=stitch.tenant_id,
        workflow_id=stitch.workflow_id,
        workflow_version=stitch.workflow_version,
        canonical_event_type=stitch.canonical_event_type,
        is_trigger=stitch.is_trigger,
        condition_event_key=stitch.condition_event_key,
        idempotency_key_field=stitch.idempotency_key_field,
        concurrency_key_field=stitch.concurrency_key_field,
        resource_hint_field=stitch.resource_hint_field,
        is_active=stitch.is_active,
    )


def _to_step_dto(step: StepRun) -> StitchStepRunSummaryDTO:
    return StitchStepRunSummaryDTO(
        step_run_id=step.id,
        node_key=step.node_key,
        status=step.status.value,
        retry_count=step.retry_count,
        app_retry_count=step.app_retry_count,
        internal_retry_count=step.internal_retry_count,
        iteration_count=step.iteration_count,
        failure_code=step.failure_code,
        failure_detail=step.failure_detail,
        created_at=step.created_at,
        finished_at=step.finished_at,
    )


def _to_run_dto(run: WorkflowRun) -> StitchRunSummaryDTO:
    steps = tuple(_to_step_dto(s) for s in run.steps.values())
    return StitchRunSummaryDTO(
        run_id=run.id,
        tenant_id=run.tenant_id,
        workflow_id=run.workflow_id,
        workflow_version=run.workflow_version,
        status=run.status.value,
        priority=run.priority.name,
        concurrency_key=run.concurrency_key,
        idempotency_key=run.idempotency_key,
        trace_id=run.trace_id,
        correlation_id=run.correlation_id,
        failure_code=run.failure_code,
        failure_detail=run.failure_detail,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        steps=steps,
    )


class ListStitchDefinitionsUseCase:
    """Lists all registered Stitch WorkflowDefinition DAGs."""

    def __init__(self, *, definition_registry: WorkflowDefinitionRegistryPort) -> None:
        self._definition_registry = definition_registry

    def execute(self) -> tuple[StitchDefinitionSummaryDTO, ...]:
        defns = self._definition_registry.list_definitions()
        dtos = [_to_definition_dto(d) for d in defns]
        dtos.sort(key=lambda d: (d.workflow_id, d.version))
        logger.info("list_stitch_definitions.completed", count=len(dtos))
        return tuple(dtos)


class GetStitchDefinitionUseCase:
    """Fetches a specific Stitch WorkflowDefinition by ID (and optional version)."""

    def __init__(self, *, definition_registry: WorkflowDefinitionRegistryPort) -> None:
        self._definition_registry = definition_registry

    def execute(
        self, query: GetStitchDefinitionQuery
    ) -> Result[StitchDefinitionSummaryDTO, IpError]:
        bound = logger.bind(workflow_id=query.workflow_id, version=query.version)
        bound.info("get_stitch_definition.received")
        if query.version is not None:
            res = self._definition_registry.get(query.workflow_id, query.version)
        else:
            res = self._definition_registry.get_latest(query.workflow_id)
        if res.is_err:
            bound.error("get_stitch_definition.not_found")
            return Result.err(
                StitchDefinitionNotFoundError.for_workflow(query.workflow_id, query.version)
            )
        defn = res.unwrap()
        bound.info("get_stitch_definition.completed", resolved_version=defn.version)
        return Result.ok(_to_definition_dto(defn))


class ListStitchesUseCase:
    """Lists all Stitches visible to a tenant (PostgreSQL Control Plane + default wildcard catalog)."""

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        uow: IpControlPlaneUnitOfWorkPort | None = None,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._uow = uow

    async def execute(self, query: ListStitchesQuery) -> tuple[StitchSummaryDTO, ...]:
        merged: dict[str, Stitch] = {
            s.id: s for s in self._stitch_catalog.list_stitches(tenant_id=query.tenant_id)
        }
        if self._uow is not None:
            async with self._uow:
                db_stitches = await self._uow.stitches.list_by_tenant(tenant_id=query.tenant_id)
                for stitch in db_stitches:
                    merged[stitch.id] = stitch

        ordered = sorted(merged.values(), key=lambda s: s.id)
        dtos = tuple(_to_stitch_dto(s) for s in ordered)
        logger.info(
            "list_stitches.completed",
            tenant_id=query.tenant_id,
            count=len(dtos),
        )
        return dtos


class RegisterStitchUseCase:
    """Validates and persists a Stitch connecting an L3 Canonical Event to a Stitch workflow."""

    def __init__(
        self,
        *,
        stitch_catalog: StitchCatalogRegistryPort,
        definition_registry: WorkflowDefinitionRegistryPort,
        uow: IpControlPlaneUnitOfWorkPort | None = None,
    ) -> None:
        self._stitch_catalog = stitch_catalog
        self._definition_registry = definition_registry
        self._uow = uow

    async def execute(self, command: RegisterStitchCommand) -> Result[StitchSummaryDTO, IpError]:
        bound = logger.bind(
            tenant_id=command.tenant_id,
            workflow_id=command.workflow_id,
            workflow_version=command.workflow_version,
            canonical_event_type=command.canonical_event_type,
        )
        bound.info("register_stitch.received")

        if not command.canonical_event_type.strip():
            bound.error("register_stitch.empty_event_type")
            return Result.err(
                InvalidConnectionConfigError(
                    field_name="canonical_event_type",
                    message="canonical_event_type must not be empty.",
                )
            )

        if not command.is_trigger and (
            command.condition_event_key is None or not command.condition_event_key.strip()
        ):
            bound.error("register_stitch.missing_condition_event_key")
            return Result.err(
                InvalidConnectionConfigError(
                    field_name="condition_event_key",
                    message="condition_event_key is required when is_trigger is False.",
                )
            )

        defn_res = self._definition_registry.get(command.workflow_id, command.workflow_version)
        if defn_res.is_err:
            bound.error("register_stitch.definition_not_found")
            return Result.err(
                StitchDefinitionNotFoundError.for_workflow(
                    command.workflow_id, command.workflow_version
                )
            )

        if command.stitch_id and command.stitch_id.strip():
            stitch_id = command.stitch_id.strip()
            if self._uow is not None:
                async with self._uow:
                    existing = await self._uow.stitches.get_by_id_global(stitch_id=stitch_id)
                    if existing is not None and existing.tenant_id != command.tenant_id:
                        bound.error(
                            "register_stitch.cross_tenant_collision",
                            existing_tenant_id=existing.tenant_id,
                        )
                        return Result.err(
                            IpError(
                                code=IpErrorCode.VALIDATION_FAILED,
                                message=f"Stitch '{stitch_id}' already exists and belongs to another tenant.",
                                http_status=409,
                                details={"stitch_id": stitch_id, "tenant_id": command.tenant_id},
                            )
                        )
            else:
                existing_in_mem = self._stitch_catalog.find_any_stitch_by_id(
                    stitch_id=stitch_id,
                )
                if (
                    existing_in_mem is not None
                    and existing_in_mem.tenant_id != command.tenant_id
                ):
                    bound.error(
                        "register_stitch.cross_tenant_collision",
                        existing_tenant_id=existing_in_mem.tenant_id,
                    )
                    return Result.err(
                        IpError(
                            code=IpErrorCode.VALIDATION_FAILED,
                            message=f"Stitch '{stitch_id}' already exists and belongs to another tenant.",
                            http_status=409,
                            details={"stitch_id": stitch_id, "tenant_id": command.tenant_id},
                        )
                    )
        else:
            stitch_id = generate_id(IpIdPrefix.STITCH.value)
        stitch = Stitch(
            id=stitch_id,
            tenant_id=command.tenant_id,
            workflow_id=command.workflow_id,
            workflow_version=command.workflow_version,
            canonical_event_type=command.canonical_event_type.strip(),
            is_trigger=command.is_trigger,
            condition_event_key=(
                command.condition_event_key.strip()
                if command.condition_event_key and command.condition_event_key.strip()
                else None
            ),
            idempotency_key_field=command.idempotency_key_field.strip() or "id",
            concurrency_key_field=(
                command.concurrency_key_field.strip()
                if command.concurrency_key_field and command.concurrency_key_field.strip()
                else None
            ),
            resource_hint_field=(
                command.resource_hint_field.strip()
                if command.resource_hint_field and command.resource_hint_field.strip()
                else None
            ),
            is_active=command.is_active,
        )
        stitch.record_registered()
        if self._uow is not None:
            async with self._uow:
                await self._uow.stitches.save(stitch)
                await self._uow.commit()
        self._stitch_catalog.register_stitch(stitch)
        bound.info("register_stitch.completed", stitch_id=stitch.id)
        return Result.ok(_to_stitch_dto(stitch))


class TriggerStitchEventUseCase:
    """Dispatches a canonical event to matching Stitches on the tenant Data Plane shard."""

    def __init__(self, *, shard_gateway: StitchShardGatewayPort) -> None:
        self._shard_gateway = shard_gateway

    async def execute(
        self, command: TriggerStitchEventCommand
    ) -> Result[DispatchCanonicalEventResultDTO, IpError]:
        trace_id = (
            command.trace_id.strip()
            if command.trace_id and command.trace_id.strip()
            else generate_id(DomainIdPrefix.IP_TRACE.value)
        )
        event_id = (
            command.event_id.strip()
            if command.event_id and command.event_id.strip()
            else generate_id(SystemIdPrefix.IDEMPOTENCY.value)
        )
        bound = logger.bind(
            tenant_id=command.tenant_id,
            canonical_event_type=command.canonical_event_type,
            event_id=event_id,
            trace_id=trace_id,
        )
        bound.info("trigger_stitch_event.received")

        res = await self._shard_gateway.dispatch_event(
            tenant_id=command.tenant_id,
            canonical_event_type=command.canonical_event_type,
            event_id=event_id,
            payload=command.payload,
            trace_id=trace_id,
            correlation_id=command.correlation_id,
        )
        if res.is_err:
            err = res.unwrap_err()
            bound.error(
                "trigger_stitch_event.failed",
                error_code=err.code.value,
                error=err.message,
            )
            return Result.err(err)

        started, deduped, signalled = res.unwrap()
        bound.info(
            "trigger_stitch_event.completed",
            started_count=len(started),
            deduplicated_count=len(deduped),
            signalled_count=len(signalled),
        )
        return Result.ok(
            DispatchCanonicalEventResultDTO(
                started_run_ids=started,
                deduplicated_run_ids=deduped,
                signalled_step_ids=signalled,
            )
        )


class GetStitchRunUseCase:
    """Inspects a durable Stitch WorkflowRun and its StepRun states on the tenant Data Plane shard."""

    def __init__(self, *, shard_gateway: StitchShardGatewayPort) -> None:
        self._shard_gateway = shard_gateway

    async def execute(self, query: GetStitchRunQuery) -> Result[StitchRunSummaryDTO, IpError]:
        bound = logger.bind(tenant_id=query.tenant_id, run_id=query.run_id)
        bound.info("get_stitch_run.received")
        res = await self._shard_gateway.get_run(
            tenant_id=query.tenant_id,
            run_id=query.run_id,
        )
        if res.is_err:
            err = res.unwrap_err()
            bound.error(
                "get_stitch_run.failed",
                error_code=err.code.value,
                error=err.message,
            )
            return Result.err(err)
        run = res.unwrap()
        bound.info("get_stitch_run.completed", status=run.status.value)
        return Result.ok(_to_run_dto(run))


__all__ = [
    "GetStitchDefinitionQuery",
    "GetStitchDefinitionUseCase",
    "GetStitchRunQuery",
    "GetStitchRunUseCase",
    "ListStitchDefinitionsUseCase",
    "ListStitchesQuery",
    "ListStitchesUseCase",
    "RegisterStitchCommand",
    "RegisterStitchUseCase",
    "StitchDefinitionSummaryDTO",
    "StitchNodeSummaryDTO",
    "StitchRunSummaryDTO",
    "StitchStepRunSummaryDTO",
    "StitchSummaryDTO",
    "TriggerStitchEventCommand",
    "TriggerStitchEventUseCase",
]
