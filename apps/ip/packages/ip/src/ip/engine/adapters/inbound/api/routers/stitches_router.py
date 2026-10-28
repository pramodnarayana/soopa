"""FastAPI router for Layer-4 Stitch definitions, stitches, event dispatch, and durable runs."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_control_plane_uow,
    get_stitch_catalog_registry,
    get_stitch_shard_gateway,
    get_workflow_definition_registry,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import from_ip_error
from ip.engine.adapters.inbound.api.dtos.stitch_dtos import (
    RegisterStitchHttpRequest,
    StitchDefinitionHttpResponse,
    StitchHttpResponse,
    StitchNodeHttpResponse,
    StitchRunHttpResponse,
    StitchStepRunHttpResponse,
    TriggerStitchEventHttpRequest,
    TriggerStitchEventHttpResponse,
)
from ip.engine.application.use_cases.stitch import (
    GetStitchDefinitionQuery,
    GetStitchDefinitionUseCase,
    GetStitchRunQuery,
    GetStitchRunUseCase,
    ListStitchDefinitionsUseCase,
    ListStitchesQuery,
    ListStitchesUseCase,
    RegisterStitchCommand,
    RegisterStitchUseCase,
    StitchDefinitionSummaryDTO,
    StitchRunSummaryDTO,
    StitchSummaryDTO,
    TriggerStitchEventCommand,
    TriggerStitchEventUseCase,
)
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
    StitchShardGatewayPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/stitches",
    tags=["IP - Stitches & Durable Workflows"],
)


def _to_definition_response(dto: StitchDefinitionSummaryDTO) -> StitchDefinitionHttpResponse:
    return StitchDefinitionHttpResponse(
        workflow_id=dto.workflow_id,
        version=dto.version,
        default_priority=dto.default_priority,
        description=dto.description,
        nodes=[
            StitchNodeHttpResponse(
                node_key=n.node_key,
                kind=n.kind,
                step_type=n.step_type,
                parents=list(n.parents),
                edge_condition=n.edge_condition,
                effect_policy=n.effect_policy,
                wait_event_key=n.wait_event_key,
                queue_name=n.queue_name,
            )
            for n in dto.nodes
        ],
    )


def _to_stitch_response(dto: StitchSummaryDTO) -> StitchHttpResponse:
    return StitchHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        workflow_id=dto.workflow_id,
        workflow_version=dto.workflow_version,
        canonical_event_type=dto.canonical_event_type,
        is_trigger=dto.is_trigger,
        condition_event_key=dto.condition_event_key,
        idempotency_key_field=dto.idempotency_key_field,
        concurrency_key_field=dto.concurrency_key_field,
        resource_hint_field=dto.resource_hint_field,
        is_active=dto.is_active,
    )


def _to_run_response(dto: StitchRunSummaryDTO) -> StitchRunHttpResponse:
    return StitchRunHttpResponse(
        run_id=dto.run_id,
        tenant_id=dto.tenant_id,
        workflow_id=dto.workflow_id,
        workflow_version=dto.workflow_version,
        status=dto.status,
        priority=dto.priority,
        concurrency_key=dto.concurrency_key,
        idempotency_key=dto.idempotency_key,
        trace_id=dto.trace_id,
        correlation_id=dto.correlation_id,
        failure_code=dto.failure_code,
        failure_detail=dto.failure_detail,
        created_at=dto.created_at,
        started_at=dto.started_at,
        finished_at=dto.finished_at,
        steps=[
            StitchStepRunHttpResponse(
                step_run_id=s.step_run_id,
                node_key=s.node_key,
                status=s.status,
                retry_count=s.retry_count,
                app_retry_count=s.app_retry_count,
                internal_retry_count=s.internal_retry_count,
                iteration_count=s.iteration_count,
                failure_code=s.failure_code,
                failure_detail=s.failure_detail,
                created_at=s.created_at,
                finished_at=s.finished_at,
            )
            for s in dto.steps
        ],
    )


@router.get("/definitions", response_model=list[StitchDefinitionHttpResponse])
async def list_stitch_definitions(
    tenant_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    definition_registry: Annotated[
        WorkflowDefinitionRegistryPort, Depends(get_workflow_definition_registry)
    ],
) -> list[StitchDefinitionHttpResponse]:
    """Lists all registered Stitch WorkflowDefinition DAGs."""
    logger.info("http_list_stitch_definitions.received", tenant_id=tenant_id)
    use_case = ListStitchDefinitionsUseCase(definition_registry=definition_registry)
    dtos = use_case.execute()
    logger.info(
        "http_list_stitch_definitions.completed",
        tenant_id=tenant_id,
        definition_count=len(dtos),
    )
    return [_to_definition_response(d) for d in dtos]


@router.get("/definitions/{workflow_id}", response_model=StitchDefinitionHttpResponse)
async def get_stitch_definition(
    tenant_id: str,
    workflow_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    definition_registry: Annotated[
        WorkflowDefinitionRegistryPort, Depends(get_workflow_definition_registry)
    ],
    version: Annotated[int | None, Query(ge=1)] = None,
) -> StitchDefinitionHttpResponse | JSONResponse:
    """Retrieves a specific Stitch WorkflowDefinition DAG by ID and optional version."""
    logger.info(
        "http_get_stitch_definition.received",
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        version=version,
    )
    use_case = GetStitchDefinitionUseCase(definition_registry=definition_registry)
    res = use_case.execute(
        GetStitchDefinitionQuery(
            workflow_id=workflow_id,
            version=version,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_get_stitch_definition.failed",
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            version=version,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info(
        "http_get_stitch_definition.completed",
        tenant_id=tenant_id,
        workflow_id=dto.workflow_id,
        version=dto.version,
    )
    return _to_definition_response(dto)


@router.get("", response_model=list[StitchHttpResponse])
async def list_stitches(
    tenant_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    stitch_catalog: Annotated[StitchCatalogRegistryPort, Depends(get_stitch_catalog_registry)],
) -> list[StitchHttpResponse]:
    """Lists all active and wildcard Stitches for the tenant."""
    logger.info("http_list_stitches.received", tenant_id=tenant_id)
    use_case = ListStitchesUseCase(stitch_catalog=stitch_catalog, uow=uow)
    dtos = await use_case.execute(ListStitchesQuery(tenant_id=tenant_id))
    logger.info(
        "http_list_stitches.completed",
        tenant_id=tenant_id,
        stitch_count=len(dtos),
    )
    return [_to_stitch_response(s) for s in dtos]


@router.post(
    "",
    response_model=StitchHttpResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_stitch(
    tenant_id: str,
    body: RegisterStitchHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    stitch_catalog: Annotated[StitchCatalogRegistryPort, Depends(get_stitch_catalog_registry)],
    definition_registry: Annotated[
        WorkflowDefinitionRegistryPort, Depends(get_workflow_definition_registry)
    ],
) -> StitchHttpResponse | JSONResponse:
    """Registers or updates a Stitch connecting a canonical event to a Stitch workflow."""
    logger.info(
        "http_register_stitch.received",
        tenant_id=tenant_id,
        workflow_id=body.workflow_id,
        workflow_version=body.workflow_version,
        canonical_event_type=body.canonical_event_type,
    )
    use_case = RegisterStitchUseCase(
        stitch_catalog=stitch_catalog,
        definition_registry=definition_registry,
        uow=uow,
    )
    res = await use_case.execute(
        RegisterStitchCommand(
            tenant_id=tenant_id,
            stitch_id=body.stitch_id,
            workflow_id=body.workflow_id,
            workflow_version=body.workflow_version,
            canonical_event_type=body.canonical_event_type,
            is_trigger=body.is_trigger,
            condition_event_key=body.condition_event_key,
            idempotency_key_field=body.idempotency_key_field,
            concurrency_key_field=body.concurrency_key_field,
            resource_hint_field=body.resource_hint_field,
            is_active=body.is_active,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_register_stitch.failed",
            tenant_id=tenant_id,
            workflow_id=body.workflow_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info(
        "http_register_stitch.completed",
        tenant_id=tenant_id,
        stitch_id=dto.id,
        workflow_id=dto.workflow_id,
    )
    return _to_stitch_response(dto)


@router.post(
    "/dispatch",
    response_model=TriggerStitchEventHttpResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def dispatch_stitch_event(
    tenant_id: str,
    body: TriggerStitchEventHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    shard_gateway: Annotated[StitchShardGatewayPort, Depends(get_stitch_shard_gateway)],
) -> TriggerStitchEventHttpResponse | JSONResponse:
    """Dispatches a canonical event to matching Stitches on the tenant Data Plane shard."""
    logger.info(
        "http_dispatch_stitch_event.received",
        tenant_id=tenant_id,
        canonical_event_type=body.canonical_event_type,
    )
    use_case = TriggerStitchEventUseCase(shard_gateway=shard_gateway)
    res = await use_case.execute(
        TriggerStitchEventCommand(
            tenant_id=tenant_id,
            canonical_event_type=body.canonical_event_type,
            payload=body.payload,
            event_id=body.event_id,
            trace_id=body.trace_id,
            correlation_id=body.correlation_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_dispatch_stitch_event.failed",
            tenant_id=tenant_id,
            canonical_event_type=body.canonical_event_type,
            error_code=err.code.value,
        )
        return from_ip_error(err)

    dto = res.unwrap()
    logger.info(
        "http_dispatch_stitch_event.completed",
        tenant_id=tenant_id,
        started_count=len(dto.started_run_ids),
        deduplicated_count=len(dto.deduplicated_run_ids),
        signalled_count=len(dto.signalled_step_ids),
    )
    return TriggerStitchEventHttpResponse(
        started_run_ids=list(dto.started_run_ids),
        deduplicated_run_ids=list(dto.deduplicated_run_ids),
        signalled_step_ids=list(dto.signalled_step_ids),
    )


@router.get("/runs/{run_id}", response_model=StitchRunHttpResponse)
async def get_stitch_run(
    tenant_id: str,
    run_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    shard_gateway: Annotated[StitchShardGatewayPort, Depends(get_stitch_shard_gateway)],
) -> StitchRunHttpResponse | JSONResponse:
    """Inspects a durable Stitch WorkflowRun and its StepRun states on the tenant Data Plane shard."""
    logger.info(
        "http_get_stitch_run.received",
        tenant_id=tenant_id,
        run_id=run_id,
    )
    use_case = GetStitchRunUseCase(shard_gateway=shard_gateway)
    res = await use_case.execute(
        GetStitchRunQuery(
            tenant_id=tenant_id,
            run_id=run_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_get_stitch_run.failed",
            tenant_id=tenant_id,
            run_id=run_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info(
        "http_get_stitch_run.completed",
        tenant_id=tenant_id,
        run_id=run_id,
        status=dto.status,
    )
    return _to_run_response(dto)
