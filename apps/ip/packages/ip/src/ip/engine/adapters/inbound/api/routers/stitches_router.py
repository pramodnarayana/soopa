"""FastAPI router for Layer-4 Stitch subscriptions."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import JSONResponse
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_control_plane_uow,
    get_stitch_catalog_registry,
    get_workflow_definition_registry,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import from_ip_error
from ip.engine.adapters.inbound.api.dtos.stitch_dtos import (
    RegisterStitchHttpRequest,
    StitchHttpResponse,
    ToggleStitchStateHttpRequest,
    UpdateStitchHttpRequest,
)
from ip.engine.adapters.inbound.api.routers.stitch_definitions_router import (
    router as definitions_router,
)
from ip.engine.adapters.inbound.api.routers.stitch_runs_router import (
    router as runs_router,
)
from ip.engine.application.use_cases.stitch import (
    DeleteStitchCommand,
    DeleteStitchUseCase,
    GetStitchQuery,
    GetStitchUseCase,
    ListStitchesQuery,
    ListStitchesUseCase,
    RegisterStitchCommand,
    RegisterStitchUseCase,
    StitchSummaryDTO,
    ToggleStitchStateCommand,
    ToggleStitchStateUseCase,
    UpdateStitchCommand,
    UpdateStitchUseCase,
)
from ip.engine.ports.outbound.stitch_catalog_registry_port import (
    StitchCatalogRegistryPort,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from orchestration.ports.inbound.step_handler_port import WorkflowDefinitionRegistryPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/stitches",
    tags=["IP - Stitches"],
)

# Mount sub-routers for definitions and runs before /{stitch_id} path parameters
router.include_router(definitions_router)
router.include_router(runs_router)


def to_stitch_http_response(dto: StitchSummaryDTO) -> StitchHttpResponse:
    """Maps a StitchSummaryDTO to StitchHttpResponse."""
    return StitchHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        canonical_event_type=dto.canonical_event_type,
        target_workflow_id=dto.target_workflow_id,
        name=dto.name,
        description=dto.description,
        mapping_spec_id=dto.mapping_spec_id,
        filter_conditions=dict(dto.filter_conditions),
        is_active=dto.is_active,
    )


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
    return [to_stitch_http_response(s) for s in dtos]


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
    """Registers or updates a Stitch connecting a canonical event to an automated workflow."""
    logger.info(
        "http_register_stitch.received",
        tenant_id=tenant_id,
        target_workflow_id=body.target_workflow_id,
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
            name=body.name,
            description=body.description,
            mapping_spec_id=body.mapping_spec_id,
            stitch_id=body.stitch_id,
            canonical_event_type=body.canonical_event_type,
            target_workflow_id=body.target_workflow_id or body.workflow_id or "",
            workflow_id=body.workflow_id or body.target_workflow_id,
            idempotency_key_field=body.idempotency_key_field,
            concurrency_key_field=body.concurrency_key_field,
            filter_conditions=body.filter_conditions,
            is_active=body.is_active,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_register_stitch.failed",
            tenant_id=tenant_id,
            target_workflow_id=body.target_workflow_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info(
        "http_register_stitch.completed",
        tenant_id=tenant_id,
        stitch_id=dto.id,
        target_workflow_id=dto.target_workflow_id,
    )
    return to_stitch_http_response(dto)


@router.get("/{stitch_id}", response_model=StitchHttpResponse)
async def get_stitch(
    tenant_id: str,
    stitch_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    stitch_catalog: Annotated[StitchCatalogRegistryPort, Depends(get_stitch_catalog_registry)],
) -> StitchHttpResponse | JSONResponse:
    """Retrieves a single Stitch by ID from the Control Plane."""
    logger.info("http_get_stitch.received", tenant_id=tenant_id, stitch_id=stitch_id)
    use_case = GetStitchUseCase(stitch_catalog=stitch_catalog, uow=uow)
    res = await use_case.execute(GetStitchQuery(tenant_id=tenant_id, stitch_id=stitch_id))
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_get_stitch.failed",
            tenant_id=tenant_id,
            stitch_id=stitch_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info("http_get_stitch.completed", tenant_id=tenant_id, stitch_id=stitch_id)
    return to_stitch_http_response(dto)


@router.patch("/{stitch_id}", response_model=StitchHttpResponse)
async def update_stitch(
    tenant_id: str,
    stitch_id: str,
    body: UpdateStitchHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    stitch_catalog: Annotated[StitchCatalogRegistryPort, Depends(get_stitch_catalog_registry)],
) -> StitchHttpResponse | JSONResponse:
    """Updates mutable Stitch properties (name, description, mapping_spec_id, filters, state)."""
    logger.info("http_update_stitch.received", tenant_id=tenant_id, stitch_id=stitch_id)
    use_case = UpdateStitchUseCase(uow=uow, stitch_catalog=stitch_catalog)
    res = await use_case.execute(
        UpdateStitchCommand(
            tenant_id=tenant_id,
            stitch_id=stitch_id,
            name=body.name,
            description=body.description,
            mapping_spec_id=body.mapping_spec_id,
            filter_conditions=body.filter_conditions,
            is_active=body.is_active,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_update_stitch.failed",
            tenant_id=tenant_id,
            stitch_id=stitch_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info("http_update_stitch.completed", tenant_id=tenant_id, stitch_id=stitch_id)
    return to_stitch_http_response(dto)


@router.patch("/{stitch_id}/state", response_model=StitchHttpResponse)
async def toggle_stitch_state(
    tenant_id: str,
    stitch_id: str,
    body: ToggleStitchStateHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    stitch_catalog: Annotated[StitchCatalogRegistryPort, Depends(get_stitch_catalog_registry)],
) -> StitchHttpResponse | JSONResponse:
    """Explicitly activates or pauses a Stitch runtime dispatch."""
    logger.info(
        "http_toggle_stitch_state.received",
        tenant_id=tenant_id,
        stitch_id=stitch_id,
        is_active=body.is_active,
    )
    use_case = ToggleStitchStateUseCase(uow=uow, stitch_catalog=stitch_catalog)
    res = await use_case.execute(
        ToggleStitchStateCommand(tenant_id=tenant_id, stitch_id=stitch_id, is_active=body.is_active)
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_toggle_stitch_state.failed",
            tenant_id=tenant_id,
            stitch_id=stitch_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    dto = res.unwrap()
    logger.info(
        "http_toggle_stitch_state.completed",
        tenant_id=tenant_id,
        stitch_id=stitch_id,
        is_active=dto.is_active,
    )
    return to_stitch_http_response(dto)


@router.delete("/{stitch_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_stitch(
    tenant_id: str,
    stitch_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    stitch_catalog: Annotated[StitchCatalogRegistryPort, Depends(get_stitch_catalog_registry)],
) -> Response:
    """Permanently deletes a Stitch and unregisters it from the runtime dispatch catalog."""
    logger.info("http_delete_stitch.received", tenant_id=tenant_id, stitch_id=stitch_id)
    use_case = DeleteStitchUseCase(uow=uow, stitch_catalog=stitch_catalog)
    res = await use_case.execute(DeleteStitchCommand(tenant_id=tenant_id, stitch_id=stitch_id))
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_delete_stitch.failed",
            tenant_id=tenant_id,
            stitch_id=stitch_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    logger.info("http_delete_stitch.completed", tenant_id=tenant_id, stitch_id=stitch_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router", "to_stitch_http_response"]
