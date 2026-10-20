"""Inbound HTTP router for Integration Platform connections and catalogs."""

from collections.abc import Iterator, Mapping
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from identity.domain.identity_context import IdentityContext
from ip.adapters.outbound.connectors.catalog_registry import ConnectorCatalogRegistry
from ip.adapters.outbound.connectors.registry_loader import create_default_catalog_registry
from ip.adapters.outbound.database.catalog_repository import SqlAlchemyCatalogRepository
from ip.adapters.outbound.database.connection_repository import SqlAlchemyConnectionRepository
from ip.application.connections.check_connection_use_case import (
    CheckConnectionCommand,
    CheckConnectionUseCase,
)
from ip.application.connections.create_connection_use_case import (
    CreateConnectionCommand,
    CreateConnectionUseCase,
)
from ip.application.connections.deactivate_connection_use_case import (
    DeactivateConnectionCommand,
    DeactivateConnectionUseCase,
)
from ip.application.connections.discover_catalog_use_case import DiscoverCatalogUseCase
from ip.application.connections.relink_connection_use_case import (
    RelinkConnectionCommand,
    RelinkConnectionUseCase,
)
from ip.application.responses import ConnectionDTO, DiscoveredCatalogDTO
from ip.domain.exceptions import (
    AuthenticationFailedException,
    CatalogDiscoveryFailedException,
    ConnectionNotFoundException,
    ConnectorNotFoundException,
    DuplicateConnectionFingerprintException,
    InvalidConnectionStateException,
)
from ip.domain.models.connection import ConnectionStatus
from ip.ports.outbound.connector_port import ConnectorPort
from security.provider import SecurityProvider
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.bootstrap.dependencies import get_db_session

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

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/connections",
    tags=["Integration Platform - Connections"],
)


class _ConnectorCatalogMapping(Mapping[str, ConnectorPort]):
    """Dynamic mapping resolving connectors from the central ConnectorCatalogRegistry."""

    def __init__(self, registry: ConnectorCatalogRegistry) -> None:
        self._registry = registry

    def __getitem__(self, key: str) -> ConnectorPort:
        try:
            return self._registry.get_connector(key)
        except ConnectorNotFoundException as exc:
            raise KeyError(key) from exc

    def __len__(self) -> int:
        return len(self._registry.list_apps())

    def __iter__(self) -> Iterator[str]:
        return (app.app_id for app in self._registry.list_apps())


_catalog_registry = create_default_catalog_registry()
_connector_mapping = _ConnectorCatalogMapping(_catalog_registry)


def _get_connectors() -> Mapping[str, ConnectorPort]:
    return _connector_mapping


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


@router.post("", response_model=ConnectionHttpResponse, status_code=status.HTTP_201_CREATED)
async def create_connection(
    tenant_id: str,
    request: CreateConnectionHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
) -> ConnectionHttpResponse:
    """Creates a new external system connection with encrypted credentials."""
    connection_repo = SqlAlchemyConnectionRepository(session)
    cipher = SecurityProvider.get_cipher()
    use_case = CreateConnectionUseCase(connection_repo=connection_repo, cipher=cipher)

    cmd = CreateConnectionCommand(
        tenant_id=tenant_id,
        app_id=request.app_id,
        name=request.name,
        auth_type=request.auth_type,
        public_config=request.public_config,
        raw_credentials=request.raw_credentials,
        endpoint_for_fingerprint=request.endpoint_for_fingerprint,
    )

    try:
        dto = await use_case.execute(cmd)
        await session.commit()
        return _map_connection_dto_to_response(dto)
    except DuplicateConnectionFingerprintException as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[ConnectionHttpResponse], status_code=status.HTTP_200_OK)
async def list_connections(
    tenant_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    connection_status: ConnectionStatus | None = Query(None, alias="status"),
) -> list[ConnectionHttpResponse]:
    """Lists connections configured for this tenant, optionally filtered by status."""
    connection_repo = SqlAlchemyConnectionRepository(session)
    connections = await connection_repo.list_by_tenant(
        tenant_id=tenant_id, status=connection_status
    )

    return [
        _map_connection_dto_to_response(
            ConnectionDTO(
                id=c.id,
                tenant_id=c.tenant_id,
                app_id=c.app_id,
                name=c.name,
                auth_type=c.auth_type.value,
                public_config=dict(c.public_config),
                status=c.status.value,
                connection_fingerprint=c.connection_fingerprint,
                token_expires_at=c.token_expires_at,
                last_refreshed_at=c.last_refreshed_at,
                last_error_code=c.last_error_code,
                last_error_message=c.last_error_message,
                created_at=c.created_at,
                updated_at=c.updated_at,
                deactivated_at=c.deactivated_at,
            )
        )
        for c in connections
    ]


@router.post("/check", response_model=ConnectionCheckHttpResponse, status_code=status.HTTP_200_OK)
async def check_connection_credentials(
    tenant_id: str,
    request: CheckConnectionHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
) -> ConnectionCheckHttpResponse:
    """Pre-flight connectivity and credential check without saving a connection."""
    connectors = _get_connectors()
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
    status_code=status.HTTP_200_OK,
)
async def get_connection(
    tenant_id: str,
    connection_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
) -> ConnectionHttpResponse:
    """Fetches details of a specific connection."""
    connection_repo = SqlAlchemyConnectionRepository(session)
    c = await connection_repo.get_by_id(connection_id)
    if not c or c.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found.",
        )

    return _map_connection_dto_to_response(
        ConnectionDTO(
            id=c.id,
            tenant_id=c.tenant_id,
            app_id=c.app_id,
            name=c.name,
            auth_type=c.auth_type.value,
            public_config=dict(c.public_config),
            status=c.status.value,
            connection_fingerprint=c.connection_fingerprint,
            token_expires_at=c.token_expires_at,
            last_refreshed_at=c.last_refreshed_at,
            last_error_code=c.last_error_code,
            last_error_message=c.last_error_message,
            created_at=c.created_at,
            updated_at=c.updated_at,
            deactivated_at=c.deactivated_at,
        )
    )


@router.post(
    "/{connection_id}/discover",
    response_model=DiscoveredCatalogHttpResponse,
    status_code=status.HTTP_200_OK,
)
async def discover_connection_catalog(
    tenant_id: str,
    connection_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
) -> DiscoveredCatalogHttpResponse:
    """Introspects the external system and stores a new schema catalog version."""
    connection_repo = SqlAlchemyConnectionRepository(session)
    catalog_repo = SqlAlchemyCatalogRepository(session)
    cipher = SecurityProvider.get_cipher()
    connectors = _get_connectors()

    # Pre-verify tenant ownership
    conn = await connection_repo.get_by_id(connection_id)
    if not conn or conn.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Connection '{connection_id}' not found.",
        )

    use_case = DiscoverCatalogUseCase(
        connection_repo=connection_repo,
        catalog_repo=catalog_repo,
        cipher=cipher,
        connectors=connectors,
    )

    try:
        dto = await use_case.execute(connection_id)
        await session.commit()
        return _map_catalog_dto_to_response(dto)
    except ConnectionNotFoundException as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ConnectorNotFoundException as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CatalogDiscoveryFailedException as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.delete(
    "/{connection_id}",
    response_model=ConnectionHttpResponse,
    status_code=status.HTTP_200_OK,
)
async def deactivate_connection(
    tenant_id: str,
    connection_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
) -> ConnectionHttpResponse:
    """Soft-deactivates an active connection."""
    connection_repo = SqlAlchemyConnectionRepository(session)
    use_case = DeactivateConnectionUseCase(connection_repo=connection_repo)

    cmd = DeactivateConnectionCommand(connection_id=connection_id, tenant_id=tenant_id)
    try:
        dto = await use_case.execute(cmd)
        await session.commit()
        return _map_connection_dto_to_response(dto)
    except ConnectionNotFoundException as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidConnectionStateException as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/{connection_id}/relink",
    response_model=ConnectionHttpResponse,
    status_code=status.HTTP_200_OK,
)
async def relink_connection(
    tenant_id: str,
    connection_id: str,
    request: RelinkConnectionHttpRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
) -> ConnectionHttpResponse:
    """Updates credentials and reactivates a disconnected or suspended connection."""
    connection_repo = SqlAlchemyConnectionRepository(session)
    cipher = SecurityProvider.get_cipher()
    use_case = RelinkConnectionUseCase(connection_repo=connection_repo, cipher=cipher)

    cmd = RelinkConnectionCommand(
        connection_id=connection_id,
        tenant_id=tenant_id,
        new_name=request.new_name,
        updated_raw_credentials=request.updated_raw_credentials,
    )
    try:
        dto = await use_case.execute(cmd)
        await session.commit()
        return _map_connection_dto_to_response(dto)
    except ConnectionNotFoundException as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AuthenticationFailedException as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
