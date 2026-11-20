"""FastAPI HTTP router for declarative Field Mapping Specs in the Control Plane."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_control_plane_uow,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import from_ip_error
from ip.engine.adapters.inbound.api.dtos.mapping_spec_dtos import (
    MappingRuleHttpDTO,
    MappingSpecHttpResponse,
    SaveMappingSpecHttpRequest,
)
from ip.engine.application.use_cases.mapping.mapping_spec_use_cases import (
    DeleteMappingSpecCommand,
    DeleteMappingSpecUseCase,
    GetMappingSpecQuery,
    GetMappingSpecUseCase,
    ListMappingSpecsQuery,
    ListMappingSpecsUseCase,
    MappingRuleDTO,
    MappingSpecDTO,
    SaveMappingSpecCommand,
    SaveMappingSpecUseCase,
)
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/mapping-specs",
    tags=["IP - Field Mapping Specifications"],
)


def _to_response_dto(dto: MappingSpecDTO) -> MappingSpecHttpResponse:
    return MappingSpecHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        name=dto.name,
        description=dto.description,
        source_type=dto.source_type,
        target_connection_id=dto.target_connection_id,
        target_entity_name=dto.target_entity_name,
        version=dto.version,
        rules=[
            MappingRuleHttpDTO(
                target_field=r.target_field,
                rule_type=r.rule_type,
                source_field=r.source_field,
                constant_value=r.constant_value,
                expression=r.expression,
            )
            for r in dto.rules
        ],
        is_active=dto.is_active,
    )


@router.post(
    "",
    response_model=MappingSpecHttpResponse,
    status_code=status.HTTP_201_CREATED,
)
async def save_mapping_spec(
    tenant_id: str,
    body: SaveMappingSpecHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> MappingSpecHttpResponse | JSONResponse:
    """Creates or versions a declarative Field Mapping Spec."""
    logger.info(
        "http_save_mapping_spec.received",
        tenant_id=tenant_id,
        name=body.name,
        target_connection_id=body.target_connection_id,
        target_entity_name=body.target_entity_name,
    )
    use_case = SaveMappingSpecUseCase(uow=uow)
    command = SaveMappingSpecCommand(
        tenant_id=tenant_id,
        mapping_spec_id=body.mapping_spec_id,
        name=body.name,
        description=body.description,
        source_type=body.source_type,
        target_connection_id=body.target_connection_id,
        target_entity_name=body.target_entity_name,
        rules=tuple(
            MappingRuleDTO(
                target_field=r.target_field,
                rule_type=r.rule_type,
                source_field=r.source_field,
                constant_value=r.constant_value,
                expression=r.expression,
            )
            for r in body.rules
        ),
        is_active=body.is_active,
    )
    res = await use_case.execute(command)
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_save_mapping_spec.failed",
            tenant_id=tenant_id,
            name=body.name,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    return _to_response_dto(res.unwrap())


@router.get(
    "/{mapping_spec_id}",
    response_model=MappingSpecHttpResponse,
)
async def get_mapping_spec(
    tenant_id: str,
    mapping_spec_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> MappingSpecHttpResponse | JSONResponse:
    """Retrieves a specific MappingSpec by ID."""
    use_case = GetMappingSpecUseCase(uow=uow)
    res = await use_case.execute(
        GetMappingSpecQuery(tenant_id=tenant_id, mapping_spec_id=mapping_spec_id)
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_get_mapping_spec.failed",
            tenant_id=tenant_id,
            mapping_spec_id=mapping_spec_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    return _to_response_dto(res.unwrap())


@router.get(
    "",
    response_model=list[MappingSpecHttpResponse],
)
async def list_mapping_specs(
    tenant_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    source_type: Annotated[str | None, Query()] = None,
    target_connection_id: Annotated[str | None, Query()] = None,
) -> list[MappingSpecHttpResponse]:
    """Lists MappingSpecs for a tenant."""
    use_case = ListMappingSpecsUseCase(uow=uow)
    dtos = await use_case.execute(
        ListMappingSpecsQuery(
            tenant_id=tenant_id,
            source_type=source_type,
            target_connection_id=target_connection_id,
        )
    )
    return [_to_response_dto(d) for d in dtos]


@router.delete(
    "/{mapping_spec_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_mapping_spec(
    tenant_id: str,
    mapping_spec_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> Response:
    """Deletes a MappingSpec if no active Stitches reference it."""
    logger.info(
        "http_delete_mapping_spec.received",
        tenant_id=tenant_id,
        mapping_spec_id=mapping_spec_id,
    )
    use_case = DeleteMappingSpecUseCase(uow=uow)
    res = await use_case.execute(
        DeleteMappingSpecCommand(
            tenant_id=tenant_id,
            mapping_spec_id=mapping_spec_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_delete_mapping_spec.failed",
            tenant_id=tenant_id,
            mapping_spec_id=mapping_spec_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    logger.info(
        "http_delete_mapping_spec.completed",
        tenant_id=tenant_id,
        mapping_spec_id=mapping_spec_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
