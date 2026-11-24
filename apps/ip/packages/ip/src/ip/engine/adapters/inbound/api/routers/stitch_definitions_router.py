"""FastAPI router for Layer-4 Stitch WorkflowDefinition DAGs."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_workflow_definition_registry,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import from_ip_error
from ip.engine.adapters.inbound.api.dtos.stitch_dtos import (
    StitchDefinitionHttpResponse,
    StitchNodeHttpResponse,
)
from ip.engine.application.use_cases.stitch import (
    GetStitchDefinitionQuery,
    GetStitchDefinitionUseCase,
    ListStitchDefinitionsUseCase,
    StitchDefinitionSummaryDTO,
)
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/definitions",
    tags=["IP - Stitch Definitions"],
)


def to_definition_http_response(dto: StitchDefinitionSummaryDTO) -> StitchDefinitionHttpResponse:
    """Maps a StitchDefinitionSummaryDTO to StitchDefinitionHttpResponse."""
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
                boundary=n.boundary,
                track=n.track,
            )
            for n in dto.nodes
        ],
    )


@router.get("", response_model=list[StitchDefinitionHttpResponse])
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
    return [to_definition_http_response(d) for d in dtos]


@router.get("/{workflow_id}", response_model=StitchDefinitionHttpResponse)
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
    return to_definition_http_response(dto)


__all__ = ["router", "to_definition_http_response"]
