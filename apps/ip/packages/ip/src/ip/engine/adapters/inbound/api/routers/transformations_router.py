"""FastAPI router for Layer-3 Normalization Transformations, Shadow Versioning, and Dry-Run Preview."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_control_plane_uow,
    get_transformer_registry,
    require_tenant_member,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import from_ip_error
from ip.engine.adapters.inbound.api.dtos.transformation_dtos import (
    BindStreamTransformationHttpRequest,
    PreviewDraftHttpResponse,
    PreviewReferenceHttpResponse,
    PreviewRejectionHttpResponse,
    PreviewStreamTransformationHttpRequest,
    PreviewStreamTransformationHttpResponse,
    PromoteTransformationVersionHttpResponse,
    RegisteredTransformerHttpResponse,
    TransformationHttpResponse,
)
from ip.engine.application.use_cases.normalization import (
    BindStreamTransformationCommand,
    BindStreamTransformationUseCase,
    GetStreamTransformationQuery,
    GetStreamTransformationUseCase,
    ListConnectionTransformationsQuery,
    ListConnectionTransformationsUseCase,
    ListRegisteredTransformersUseCase,
    PreviewStreamTransformationCommand,
    PreviewStreamTransformationUseCase,
    PromoteTransformationVersionCommand,
    PromoteTransformationVersionUseCase,
    TransformationDTO,
)
from ip.engine.ports.outbound.transformer_port import TransformerRegistryPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/transformations",
    tags=["IP - Transformations"],
)


def _to_transformation_response(
    dto: TransformationDTO,
    *,
    was_created: bool | None = None,
) -> TransformationHttpResponse:
    return TransformationHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        connection_id=dto.connection_id,
        stream=dto.stream,
        transformation_id=dto.transformation_id,
        transformation_version=dto.transformation_version,
        mode=dto.mode.value,
        shadow_transformation_version=dto.shadow_transformation_version,
        was_created=was_created,
    )


@router.get("/transformers", response_model=list[RegisteredTransformerHttpResponse])
async def list_registered_transformers(
    tenant_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    transformer_registry: Annotated[TransformerRegistryPort, Depends(get_transformer_registry)],
) -> list[RegisteredTransformerHttpResponse]:
    """Lists all registered pure L3 normalization code transformers and their versions."""
    logger.info("http_list_registered_transformers.received", tenant_id=tenant_id)
    use_case = ListRegisteredTransformersUseCase(transformer_registry=transformer_registry)
    dtos = use_case.execute()
    logger.info(
        "http_list_registered_transformers.completed",
        tenant_id=tenant_id,
        transformer_count=len(dtos),
    )
    return [
        RegisteredTransformerHttpResponse(
            transformation_id=d.transformation_id,
            transformation_version=d.transformation_version,
            target_types=list(d.target_types),
        )
        for d in dtos
    ]


@router.get(
    "/connections/{connection_id}",
    response_model=list[TransformationHttpResponse],
)
async def list_connection_transformations(
    tenant_id: str,
    connection_id: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> list[TransformationHttpResponse] | JSONResponse:
    """Lists all configured stream transformations for a connection."""
    logger.info(
        "http_list_connection_transformations.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
    )
    use_case = ListConnectionTransformationsUseCase(control_plane_uow=cp_uow)
    res = await use_case.execute(
        ListConnectionTransformationsQuery(
            tenant_id=tenant_id,
            connection_id=connection_id,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_list_connection_transformations.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    transformations = res.unwrap()
    logger.info(
        "http_list_connection_transformations.completed",
        tenant_id=tenant_id,
        connection_id=connection_id,
        transformation_count=len(transformations),
    )
    return [_to_transformation_response(t) for t in transformations]


@router.get(
    "/connections/{connection_id}/streams/{stream}",
    response_model=TransformationHttpResponse,
)
async def get_stream_transformation(
    tenant_id: str,
    connection_id: str,
    stream: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> TransformationHttpResponse | JSONResponse:
    """Retrieves the stream transformation for a specific connection stream."""
    logger.info(
        "http_get_stream_transformation.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream=stream,
    )
    use_case = GetStreamTransformationUseCase(control_plane_uow=cp_uow)
    res = await use_case.execute(
        GetStreamTransformationQuery(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_get_stream_transformation.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            error_code=err.code.value,
        )
        return from_ip_error(err)
    transformation = res.unwrap()
    logger.info(
        "http_get_stream_transformation.completed",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream=stream,
        id=transformation.id,
    )
    return _to_transformation_response(transformation)


@router.put(
    "/connections/{connection_id}/streams/{stream}",
    response_model=TransformationHttpResponse,
)
async def bind_stream_transformation(
    tenant_id: str,
    connection_id: str,
    stream: str,
    body: BindStreamTransformationHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    transformer_registry: Annotated[TransformerRegistryPort, Depends(get_transformer_registry)],
) -> TransformationHttpResponse | JSONResponse:
    """Configures or updates an L3 transformer version and optional shadow version for a connection stream."""
    logger.info(
        "http_bind_stream_transformation.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream=stream,
        transformation_id=body.transformation_id,
        transformation_version=body.transformation_version,
        mode=body.mode.value,
        shadow_transformation_version=body.shadow_transformation_version,
    )
    use_case = BindStreamTransformationUseCase(
        control_plane_uow=cp_uow,
        transformer_registry=transformer_registry,
    )
    res = await use_case.execute(
        BindStreamTransformationCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            transformation_id=body.transformation_id,
            transformation_version=body.transformation_version,
            mode=body.mode,
            shadow_transformation_version=body.shadow_transformation_version,
        )
    )
    if res.is_err:
        bind_err = res.unwrap_err()
        logger.error(
            "http_bind_stream_transformation.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            error_code=bind_err.code.value,
        )
        return from_ip_error(bind_err)

    dto = res.unwrap()
    logger.info(
        "http_bind_stream_transformation.completed",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream=stream,
        id=dto.id,
    )
    return TransformationHttpResponse(
        id=dto.id,
        tenant_id=tenant_id,
        connection_id=dto.connection_id,
        stream=dto.stream,
        transformation_id=dto.transformation_id,
        transformation_version=dto.transformation_version,
        mode=dto.mode,
        shadow_transformation_version=dto.shadow_transformation_version,
    )


@router.post(
    "/connections/{connection_id}/streams/{stream}/promote",
    response_model=PromoteTransformationVersionHttpResponse,
)
async def promote_transformation_version(
    tenant_id: str,
    connection_id: str,
    stream: str,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> PromoteTransformationVersionHttpResponse | JSONResponse:
    """Promotes a configured shadow transformation version to the active version for a stream."""
    logger.info(
        "http_promote_transformation_version.received",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream=stream,
    )
    use_case = PromoteTransformationVersionUseCase(control_plane_uow=cp_uow)
    res = await use_case.execute(
        PromoteTransformationVersionCommand(
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_promote_transformation_version.failed",
            tenant_id=tenant_id,
            connection_id=connection_id,
            stream=stream,
            error_code=err.code.value,
        )
        return from_ip_error(err)

    dto = res.unwrap()
    logger.info(
        "http_promote_transformation_version.completed",
        tenant_id=tenant_id,
        connection_id=connection_id,
        stream=stream,
        promoted_version=dto.promoted_version,
    )
    return PromoteTransformationVersionHttpResponse(
        id=dto.id,
        connection_id=dto.connection_id,
        stream=dto.stream,
        transformation_id=dto.transformation_id,
        promoted_version=dto.promoted_version,
        previous_version=dto.previous_version,
    )


@router.post(
    "/preview",
    response_model=PreviewStreamTransformationHttpResponse,
)
async def preview_stream_transformation(
    tenant_id: str,
    body: PreviewStreamTransformationHttpRequest,
    _identity: Annotated[IdentityContext, Depends(require_tenant_member)],
    transformer_registry: Annotated[TransformerRegistryPort, Depends(get_transformer_registry)],
) -> PreviewStreamTransformationHttpResponse | JSONResponse:
    """Executes a pure dry-run of an L3 transformer (and optional shadow version) against a sample payload."""
    logger.info(
        "http_preview_stream_transformation.received",
        tenant_id=tenant_id,
        transformation_id=body.transformation_id,
        transformation_version=body.transformation_version,
        shadow_transformation_version=body.shadow_transformation_version,
    )
    use_case = PreviewStreamTransformationUseCase(transformer_registry=transformer_registry)
    res = use_case.execute(
        PreviewStreamTransformationCommand(
            tenant_id=tenant_id,
            connection_id=body.connection_id,
            stream=body.stream,
            transformation_id=body.transformation_id,
            transformation_version=body.transformation_version,
            record_key=body.record_key,
            sample_payload=body.sample_payload,
            shadow_transformation_version=body.shadow_transformation_version,
        )
    )
    if res.is_err:
        err = res.unwrap_err()
        logger.error(
            "http_preview_stream_transformation.failed",
            tenant_id=tenant_id,
            transformation_id=body.transformation_id,
            transformation_version=body.transformation_version,
            error_code=err.code.value,
        )
        return from_ip_error(err)

    dto = res.unwrap()
    logger.info(
        "http_preview_stream_transformation.completed",
        tenant_id=tenant_id,
        transformation_id=dto.transformation_id,
        transformation_version=dto.transformation_version,
        draft_count=len(dto.drafts),
        rejection_count=len(dto.rejections),
    )
    return PreviewStreamTransformationHttpResponse(
        transformation_id=dto.transformation_id,
        transformation_version=dto.transformation_version,
        drafts=[
            PreviewDraftHttpResponse(
                canonical_type=d.canonical_type,
                source_id=d.source_id,
                fields=d.fields,
                extensions=d.extensions,
                references=[
                    PreviewReferenceHttpResponse(
                        field_name=ref.field_name,
                        target_canonical_type=ref.target_canonical_type,
                        target_source_id=ref.target_source_id,
                    )
                    for ref in d.references
                ],
            )
            for d in dto.drafts
        ],
        rejections=[
            PreviewRejectionHttpResponse(
                reason=r.reason,
                field_path=r.field_path,
                detail=r.detail,
            )
            for r in dto.rejections
        ],
        shadow_transformation_version=dto.shadow_transformation_version,
        shadow_diffs={key: diff.to_json_dict() for key, diff in dto.shadow_diffs.items()},
    )
