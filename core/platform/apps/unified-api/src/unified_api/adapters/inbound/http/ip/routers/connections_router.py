"""Inbound HTTP router for Integration Platform connections and catalogs."""

from collections.abc import Mapping
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Response, status
from identity.domain.identity_context import IdentityContext
from ip.engine.application.dto import ConnectionDTO, DiscoveredCatalogDTO
from ip.engine.application.use_cases.connections.check_connection_use_case import (
    CheckConnectionCommand,
    CheckConnectionUseCase,
)
from ip.engine.application.use_cases.connections.create_connection_use_case import (
    CreateConnectionCommand,
    CreateConnectionUseCase,
)
from ip.engine.application.use_cases.connections.deactivate_connection_use_case import (
    DeactivateConnectionCommand,
    DeactivateConnectionUseCase,
)
from ip.engine.application.use_cases.connections.discover_catalog_use_case import (
    DiscoverCatalogUseCase,
)
from ip.engine.application.use_cases.connections.get_connection_use_case import (
    GetConnectionQuery,
    GetConnectionUseCase,
)
from ip.engine.application.use_cases.connections.list_connections_use_case import (
    ListConnectionsQuery,
    ListConnectionsUseCase,
)
from ip.engine.application.use_cases.connections.relink_connection_use_case import (
    RelinkConnectionCommand,
    RelinkConnectionUseCase,
)
from ip.engine.domain.enums import ConnectionStatus
from ip.engine.domain.exceptions import ConnectionNotFoundError, IpErrorCode
from ip.engine.ports.outbound.connector_port import ConnectorPort
from ip.engine.ports.outbound.uow import IpControlPlaneUnitOfWorkPort
from security.ports.cipher_port import CipherPort

from unified_api.adapters.inbound.http.dependencies.ip.database import (
    get_ip_control_plane_uow,
)
from unified_api.adapters.inbound.http.dependencies.ip.services import (
    get_cipher,
    get_connectors,
)
from unified_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from unified_api.adapters.inbound.http.ip.dtos.connection_dtos import (
    CheckConnectionHttpRequest,
    ConnectionCheckHttpResponse,
    ConnectionHttpResponse,
    CreateConnectionHttpRequest,
    DiscoveredCatalogHttpResponse,
    RelinkConnectionHttpRequest,
    StreamFieldHttpResponse,
    StreamSchemaHttpResponse,
)
from unified_api.adapters.inbound.http.ip.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
    to_error_response,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/connections",
    tags=["Integration Platform - Connections"],
)


def _map_connection_dto_to_response(dto: ConnectionDTO) -> ConnectionHttpResponse:
    return ConnectionHttpResponse(
        id=dto.id,
        tenant_id=dto.tenant_id,
        app_id=dto.app_id,
        name=dto.name,
        auth_type=dto.auth_type,
        public_config=dict(dto.public_config),
        status=dto.status,
        connection_fingerprint=dto.connection_fingerprint,
        token_expires_at=dto.token_expires_at,
        last_refreshed_at=dto.last_refreshed_at,
        last_error_code=dto.last_error_code,
        last_error_message=dto.last_error_message,
        created_at=dto.created_at,
        updated_at=dto.updated_at,
        deactivated_at=dto.deactivated_at,
    )


def _map_catalog_dto_to_response(dto: DiscoveredCatalogDTO) -> DiscoveredCatalogHttpResponse:
    return DiscoveredCatalogHttpResponse(
        connection_id=dto.connection_id,
        catalog_version=dto.catalog_version,
        catalog_hash=dto.catalog_hash,
        discovered_at=dto.discovered_at,
        streams=[
            StreamSchemaHttpResponse(
                name=s.name,
                fields=[
                    StreamFieldHttpResponse(
                        name=f.name,
                        data_type=f.data_type,
                        nullable=f.nullable,
                        description=f.description,
                    )
                    for f in s.fields
                ],
                primary_key=list(s.primary_key),
                cursor_field=s.cursor_field,
                supported_sync_modes=list(s.supported_sync_modes),
            )
            for s in dto.streams
        ],
    )


@router.post(
    "",
    response_model=ConnectionHttpResponse,
    responses={
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_201_CREATED,
)
async def create_connection(
    tenant_id: str,
    request: CreateConnectionHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    ip_cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    cipher: Annotated[CipherPort, Depends(get_cipher)],
) -> ConnectionHttpResponse | Response:
    """Creates a new external system connection with encrypted credentials."""
    use_case = CreateConnectionUseCase(uow=ip_cp_uow, cipher=cipher)

    cmd = CreateConnectionCommand(
        tenant_id=tenant_id,
        app_id=request.app_id,
        name=request.name,
        auth_type=request.auth_type,
        public_config=request.public_config,
        raw_credentials=request.raw_credentials,
        endpoint_for_fingerprint=request.endpoint_for_fingerprint,
    )

    result = await use_case.execute(cmd)
    if not result.success:
        if result.error is not None:
            return from_ip_error(result.error)
        status_code = (
            status.HTTP_409_CONFLICT
            if result.error_code == IpErrorCode.DUPLICATE_FINGERPRINT.value
            else status.HTTP_400_BAD_REQUEST
        )
        return to_error_response(
            status_code=status_code,
            code=result.error_code or IpErrorCode.INVALID_CONFIG.value,
            message=result.error_message or "Connection creation failed",
        )
    if result.connection is None:
        return to_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="Connection created but payload was omitted.",
        )
    return _map_connection_dto_to_response(result.connection)


@router.get("", response_model=list[ConnectionHttpResponse], status_code=status.HTTP_200_OK)
async def list_connections(
    tenant_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    ip_cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    connection_status: ConnectionStatus | None = Query(None, alias="status"),
) -> list[ConnectionHttpResponse]:
    """Lists connections configured for this tenant, optionally filtered by status."""
    use_case = ListConnectionsUseCase(uow=ip_cp_uow)
    dtos = await use_case.execute(
        ListConnectionsQuery(tenant_id=tenant_id, status=connection_status)
    )
    return [_map_connection_dto_to_response(dto) for dto in dtos]


@router.post("/check", response_model=ConnectionCheckHttpResponse, status_code=status.HTTP_200_OK)
async def check_connection_credentials(
    tenant_id: str,
    request: CheckConnectionHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    connectors: Annotated[Mapping[str, ConnectorPort], Depends(get_connectors)],
) -> ConnectionCheckHttpResponse:
    """Pre-flight connectivity and credential check without saving a connection."""
    use_case = CheckConnectionUseCase(connectors=connectors)

    cmd = CheckConnectionCommand(
        app_id=request.app_id,
        auth_type=request.auth_type,
        public_config=request.public_config,
        raw_credentials=request.raw_credentials,
    )

    result = await use_case.execute(cmd)
    return ConnectionCheckHttpResponse(
        success=result.success,
        status=result.status,
        message=result.message,
        error_code=result.error_code,
    )


@router.get(
    "/{connection_id}",
    response_model=ConnectionHttpResponse,
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_200_OK,
)
async def get_connection(
    tenant_id: str,
    connection_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    ip_cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ConnectionHttpResponse | Response:
    """Fetches details of a specific connection."""
    use_case = GetConnectionUseCase(uow=ip_cp_uow)
    result = await use_case.execute(
        GetConnectionQuery(tenant_id=tenant_id, connection_id=connection_id)
    )
    if not result.success or result.connection is None:
        return from_ip_error(result.error or ConnectionNotFoundError.for_id(connection_id))

    return _map_connection_dto_to_response(result.connection)


@router.post(
    "/{connection_id}/discover",
    response_model=DiscoveredCatalogHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_502_BAD_GATEWAY: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_200_OK,
)
async def discover_connection_catalog(
    tenant_id: str,
    connection_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    ip_cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    cipher: Annotated[CipherPort, Depends(get_cipher)],
    connectors: Annotated[Mapping[str, ConnectorPort], Depends(get_connectors)],
) -> DiscoveredCatalogHttpResponse | Response:
    """Introspects the external system and stores a new schema catalog version."""
    use_case = DiscoverCatalogUseCase(
        uow=ip_cp_uow,
        cipher=cipher,
        connectors=connectors,
    )

    dto = await use_case.execute(connection_id=connection_id, tenant_id=tenant_id)
    if not dto.success:
        if dto.error is not None:
            status_override = (
                status.HTTP_404_NOT_FOUND
                if dto.error.code
                in (IpErrorCode.CONNECTION_NOT_FOUND, IpErrorCode.CONNECTOR_NOT_FOUND)
                else status.HTTP_502_BAD_GATEWAY
            )
            return from_ip_error(dto.error, status_code_override=status_override)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if dto.error_code
            in (IpErrorCode.CONNECTION_NOT_FOUND.value, IpErrorCode.CONNECTOR_NOT_FOUND.value)
            else status.HTTP_502_BAD_GATEWAY
        )
        return to_error_response(
            status_code=status_code,
            code=dto.error_code or IpErrorCode.CATALOG_DISCOVERY_FAILED.value,
            message=dto.error_message or "Catalog discovery failed",
        )
    return _map_catalog_dto_to_response(dto)


@router.delete(
    "/{connection_id}",
    response_model=ConnectionHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_200_OK,
)
async def deactivate_connection(
    tenant_id: str,
    connection_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    ip_cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
) -> ConnectionHttpResponse | Response:
    """Soft-deactivates an active connection."""
    use_case = DeactivateConnectionUseCase(uow=ip_cp_uow)

    cmd = DeactivateConnectionCommand(connection_id=connection_id, tenant_id=tenant_id)
    result = await use_case.execute(cmd)
    if not result.success:
        if result.error is not None:
            return from_ip_error(result.error)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if result.error_code == IpErrorCode.CONNECTION_NOT_FOUND.value
            else status.HTTP_409_CONFLICT
        )
        return to_error_response(
            status_code=status_code,
            code=result.error_code or IpErrorCode.INVALID_CONNECTION_STATE.value,
            message=result.error_message or "Connection deactivation failed",
        )
    if result.connection is None:
        return to_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="Connection deactivated but payload was omitted.",
        )
    return _map_connection_dto_to_response(result.connection)


@router.post(
    "/{connection_id}/relink",
    response_model=ConnectionHttpResponse,
    responses={
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
        status.HTTP_409_CONFLICT: {"model": ApiErrorHttpResponse},
        status.HTTP_422_UNPROCESSABLE_ENTITY: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_200_OK,
)
async def relink_connection(
    tenant_id: str,
    connection_id: str,
    request: RelinkConnectionHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    ip_cp_uow: Annotated[IpControlPlaneUnitOfWorkPort, Depends(get_ip_control_plane_uow)],
    cipher: Annotated[CipherPort, Depends(get_cipher)],
) -> ConnectionHttpResponse | Response:
    """Updates credentials and reactivates a disconnected or suspended connection."""
    use_case = RelinkConnectionUseCase(uow=ip_cp_uow, cipher=cipher)

    cmd = RelinkConnectionCommand(
        connection_id=connection_id,
        tenant_id=tenant_id,
        new_name=request.new_name,
        updated_raw_credentials=request.updated_raw_credentials,
    )
    result = await use_case.execute(cmd)
    if not result.success:
        if result.error is not None:
            return from_ip_error(result.error)
        status_code = (
            status.HTTP_404_NOT_FOUND
            if result.error_code == IpErrorCode.CONNECTION_NOT_FOUND.value
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        return to_error_response(
            status_code=status_code,
            code=result.error_code or IpErrorCode.INVALID_CONNECTION_STATE.value,
            message=result.error_message or "Connection relink failed",
        )
    if result.connection is None:
        return to_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="INTERNAL_ERROR",
            message="Connection relinked but payload was omitted.",
        )
    return _map_connection_dto_to_response(result.connection)
