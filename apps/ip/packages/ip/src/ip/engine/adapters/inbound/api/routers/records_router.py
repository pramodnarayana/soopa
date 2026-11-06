"""Inbound HTTP router for inspecting Layer 1, Layer 2, Layer 3, and GEM records with role-based access control."""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, Query, Request, Response, status
from identity.domain.identity_context import IdentityContext
from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_data_plane_uow_provider,
    require_canonical_records_read,
    require_raw_records_read,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import ApiErrorHttpResponse, from_ip_error
from ip.engine.adapters.inbound.api.dtos.trace_dtos import (
    GlobalEntityMapHttpResponse,
    InboundRecordHttpResponse,
    NormalizedRecordHttpResponse,
    ReplicaRecordHttpResponse,
    map_entity_mapping_to_http,
    map_inbound_record_to_http,
    map_normalized_record_to_http,
    map_replica_record_to_http,
)
from ip.engine.application.use_cases.records import (
    ListGlobalEntityMapQuery,
    ListGlobalEntityMapUseCase,
    ListInboundRecordsQuery,
    ListInboundRecordsUseCase,
    ListNormalizedRecordsQuery,
    ListNormalizedRecordsUseCase,
    ListReplicaRecordsQuery,
    ListReplicaRecordsUseCase,
)
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/records",
    tags=["Integration Platform - Records & GEM"],
)


@router.get(
    "/normalized",
    response_model=list[NormalizedRecordHttpResponse],
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_200_OK,
)
async def list_normalized_records(
    tenant_id: str,
    request: Request,
    context: Annotated[IdentityContext, Depends(require_canonical_records_read)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    connection_id: Annotated[
        str | None, Query(description="Filter by source connection ID")
    ] = None,
    canonical_type: Annotated[
        str | None, Query(description="Filter by canonical entity type")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NormalizedRecordHttpResponse] | Response:
    """Lists Layer 3 Normalized canonical records. Accessible to both Customer Support and Customers."""
    _ = context
    try:
        ucp_tenant_id: str = request.state.ucp_tenant_id
    except AttributeError:
        ucp_tenant_id = tenant_id

    log = logger.bind(
        tenant_id=ucp_tenant_id,
        path_tenant_id=tenant_id,
        connection_id=connection_id,
        canonical_type=canonical_type,
        limit=limit,
        offset=offset,
    )
    log.info("ip_list_normalized_records_http.received")

    use_case = ListNormalizedRecordsUseCase(uow_provider=uow_provider)
    result = await use_case.execute(
        ListNormalizedRecordsQuery(
            tenant_id=ucp_tenant_id,
            connection_id=connection_id,
            canonical_type=canonical_type,
            limit=limit,
            offset=offset,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_list_normalized_records_http.failed", error_code=err.code.value)
        return from_ip_error(err)

    records = result.unwrap()
    log.info("ip_list_normalized_records_http.completed", count=len(records))
    return [map_normalized_record_to_http(r) for r in records]


@router.get(
    "/gem",
    response_model=list[GlobalEntityMapHttpResponse],
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse}},
    status_code=status.HTTP_200_OK,
)
async def list_gem_records(
    tenant_id: str,
    request: Request,
    context: Annotated[IdentityContext, Depends(require_canonical_records_read)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    source_connection_id: Annotated[
        str | None, Query(description="Filter by source connection ID")
    ] = None,
    entity_domain: Annotated[str | None, Query(description="Filter by entity domain")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GlobalEntityMapHttpResponse] | Response:
    """Lists Global Entity Map (GEM) identity crosswalk records. Accessible to both Customer Support and Customers."""
    _ = context
    try:
        ucp_tenant_id: str = request.state.ucp_tenant_id
    except AttributeError:
        ucp_tenant_id = tenant_id

    log = logger.bind(
        tenant_id=ucp_tenant_id,
        path_tenant_id=tenant_id,
        source_connection_id=source_connection_id,
        entity_domain=entity_domain,
        limit=limit,
        offset=offset,
    )
    log.info("ip_list_gem_records_http.received")

    use_case = ListGlobalEntityMapUseCase(uow_provider=uow_provider)
    result = await use_case.execute(
        ListGlobalEntityMapQuery(
            tenant_id=ucp_tenant_id,
            entity_domain=entity_domain,
            source_connection_id=source_connection_id,
            limit=limit,
            offset=offset,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_list_gem_records_http.failed", error_code=err.code.value)
        return from_ip_error(err)

    entries = result.unwrap()
    log.info("ip_list_gem_records_http.completed", count=len(entries))
    return [map_entity_mapping_to_http(e) for e in entries]


@router.get(
    "/replica",
    response_model=list[ReplicaRecordHttpResponse],
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_200_OK,
)
async def list_replica_records(
    tenant_id: str,
    request: Request,
    context: Annotated[IdentityContext, Depends(require_raw_records_read)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    connection_id: Annotated[str | None, Query(description="Filter by connection ID")] = None,
    stream: Annotated[str | None, Query(description="Filter by stream name")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ReplicaRecordHttpResponse] | Response:
    """Lists Layer 2 Universal Replica records. RESTRICTED to Customer Support (blocked for Customer)."""
    _ = context
    try:
        ucp_tenant_id: str = request.state.ucp_tenant_id
    except AttributeError:
        ucp_tenant_id = tenant_id

    log = logger.bind(
        tenant_id=ucp_tenant_id,
        path_tenant_id=tenant_id,
        connection_id=connection_id,
        stream=stream,
        limit=limit,
        offset=offset,
    )
    log.info("ip_list_replica_records_http.received")

    use_case = ListReplicaRecordsUseCase(uow_provider=uow_provider)
    result = await use_case.execute(
        ListReplicaRecordsQuery(
            tenant_id=ucp_tenant_id,
            connection_id=connection_id,
            stream=stream,
            limit=limit,
            offset=offset,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_list_replica_records_http.failed", error_code=err.code.value)
        return from_ip_error(err)

    records = result.unwrap()
    log.info("ip_list_replica_records_http.completed", count=len(records))
    return [map_replica_record_to_http(r) for r in records]


@router.get(
    "/inbound",
    response_model=list[InboundRecordHttpResponse],
    responses={
        status.HTTP_403_FORBIDDEN: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
    status_code=status.HTTP_200_OK,
)
async def list_inbound_records(
    tenant_id: str,
    request: Request,
    context: Annotated[IdentityContext, Depends(require_raw_records_read)],
    uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    connection_id: Annotated[str | None, Query(description="Filter by connection ID")] = None,
    stream_name: Annotated[str | None, Query(description="Filter by stream name")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    hydrate_payloads: Annotated[
        bool, Query(description="Hydrate offloaded S3 request/response bodies")
    ] = False,
) -> list[InboundRecordHttpResponse] | Response:
    """Lists Layer 1 Inbound Wire records. RESTRICTED to Customer Support (blocked for Customer)."""
    _ = context
    try:
        ucp_tenant_id: str = request.state.ucp_tenant_id
    except AttributeError:
        ucp_tenant_id = tenant_id

    log = logger.bind(
        tenant_id=ucp_tenant_id,
        path_tenant_id=tenant_id,
        connection_id=connection_id,
        stream_name=stream_name,
        limit=limit,
        offset=offset,
    )
    log.info("ip_list_inbound_records_http.received")

    use_case = ListInboundRecordsUseCase(uow_provider=uow_provider)
    result = await use_case.execute(
        ListInboundRecordsQuery(
            tenant_id=ucp_tenant_id,
            connection_id=connection_id,
            stream_name=stream_name,
            limit=limit,
            offset=offset,
            hydrate_payloads=hydrate_payloads,
        )
    )
    if result.is_err:
        err = result.unwrap_err()
        log.error("ip_list_inbound_records_http.failed", error_code=err.code.value)
        return from_ip_error(err)

    records = result.unwrap()
    log.info("ip_list_inbound_records_http.completed", count=len(records))
    return [map_inbound_record_to_http(r) for r in records]
