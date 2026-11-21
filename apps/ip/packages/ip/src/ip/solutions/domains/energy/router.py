"""Inbound HTTP router for High-Volume Smart Grid Meter Reading Inspection and Search."""

from __future__ import annotations

from typing import Annotated

import structlog
from database.olap.ports.olap_client_port import OlapClientPort
from fastapi import APIRouter, Depends, Query, Response, status
from identity.domain.identity_context import IdentityContext

from ip.engine.adapters.inbound.api.dependencies import (
    get_ip_data_plane_uow_provider,
    get_olap_client,
    require_canonical_records_read,
)
from ip.engine.adapters.inbound.api.dtos.error_dtos import (
    ApiErrorHttpResponse,
    from_ip_error,
)
from ip.engine.domain.exceptions import TenantShardNotFoundError
from ip.engine.ports.outbound.uow import IpDataPlaneUnitOfWorkProviderPort
from ip.solutions.domains.energy.inspection_dto import (
    BatchReadingSampleHttpResponse,
    MeterReadingSearchFilterDTO,
    MeterReadingSearchHttpResponse,
    MeterReadingSummaryHttpDTO,
)
from ip.solutions.domains.energy.inspection_service import (
    MeterReadingInspectionService,
)

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/ip/meter-readings",
    tags=["Integration Platform - Meter Reading Inspection"],
)


@router.get(
    "/search",
    response_model=MeterReadingSearchHttpResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
)
async def search_meter_readings(
    tenant_id: str,
    _context: Annotated[IdentityContext, Depends(require_canonical_records_read)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    olap_client: Annotated[OlapClientPort, Depends(get_olap_client)],
    meter_serial_number: Annotated[
        str | None, Query(description="Meter device serial number")
    ] = None,
    service_point_id: Annotated[str | None, Query(description="Service point identifier")] = None,
    quality_status: Annotated[str | None, Query(description="CIM quality status filter")] = None,
    correlation_id: Annotated[str | None, Query(description="Correlation ID filter")] = None,
    limit: Annotated[int, Query(ge=1, le=1000, description="Max readings to return")] = 50,
    offset: Annotated[int, Query(ge=0, description="Offset for pagination")] = 0,
) -> MeterReadingSearchHttpResponse | Response:
    """Executes sub-2-second primary key search across ClickHouse Inverted Index."""
    logger.info(
        "ip_meter_readings_search.received",
        tenant_id=tenant_id,
        meter_serial_number=meter_serial_number,
        service_point_id=service_point_id,
    )

    shard_res = await dp_uow_provider.resolve_shard_info(tenant_id)
    if not shard_res.is_ok:
        err = shard_res.error or TenantShardNotFoundError(
            message=f"No active data plane shard found for tenant '{tenant_id}'",
            tenant_id=tenant_id,
        )
        return from_ip_error(err, status_code_override=status.HTTP_404_NOT_FOUND)
    shard_id, shard_dsn = shard_res.unwrap()

    async with dp_uow_provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
        service = MeterReadingInspectionService(
            olap_client=olap_client,
            manifest_repo=uow.batch_manifests,
        )
        filter_dto = MeterReadingSearchFilterDTO(
            tenant_id=tenant_id,
            meter_serial_number=meter_serial_number,
            service_point_id=service_point_id,
            quality_status=quality_status,
            correlation_id=correlation_id,
            limit=limit,
            offset=offset,
        )
        summary_dto, rows = await service.search(filter_dto)

        summary_http = MeterReadingSummaryHttpDTO(
            meter_serial_number=summary_dto.meter_serial_number,
            tenant_id=summary_dto.tenant_id,
            latest_interval_end_utc=summary_dto.latest_interval_end_utc,
            active_quality_status=summary_dto.active_quality_status,
            total_readings_24h=summary_dto.total_readings_24h,
            total_kwh_delivered_24h=summary_dto.total_kwh_delivered_24h,
            total_kwh_received_24h=summary_dto.total_kwh_received_24h,
            average_voltage_v=summary_dto.average_voltage_v,
            last_delivery_receipt_id=summary_dto.last_delivery_receipt_id,
        )
        readings_list: list[dict[str, object]] = []
        for r in rows:
            readings_list.append(dict(r))

        return MeterReadingSearchHttpResponse(
            summary=summary_http,
            readings=readings_list,
        )


@router.get(
    "/batches/{batch_id}/micro-sample",
    response_model=BatchReadingSampleHttpResponse,
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ApiErrorHttpResponse},
        status.HTTP_404_NOT_FOUND: {"model": ApiErrorHttpResponse},
    },
)
async def get_batch_micro_sample(
    tenant_id: str,
    batch_id: str,
    _context: Annotated[IdentityContext, Depends(require_canonical_records_read)],
    dp_uow_provider: Annotated[
        IpDataPlaneUnitOfWorkProviderPort, Depends(get_ip_data_plane_uow_provider)
    ],
    olap_client: Annotated[OlapClientPort, Depends(get_olap_client)],
    limit: Annotated[int, Query(ge=1, le=100, description="Number of sample rows")] = 50,
    offset: Annotated[int, Query(ge=0, description="Offset")] = 0,
) -> BatchReadingSampleHttpResponse | Response:
    """Combines Tier 1 Manifest Card with Tier 3 50-row ClickHouse Grid in < 50ms."""
    logger.info(
        "ip_meter_readings_micro_sample.received",
        tenant_id=tenant_id,
        batch_id=batch_id,
        limit=limit,
    )

    shard_res = await dp_uow_provider.resolve_shard_info(tenant_id)
    if not shard_res.is_ok:
        err = shard_res.error or TenantShardNotFoundError(
            message=f"No active data plane shard found for tenant '{tenant_id}'",
            tenant_id=tenant_id,
        )
        return from_ip_error(err, status_code_override=status.HTTP_404_NOT_FOUND)
    shard_id, shard_dsn = shard_res.unwrap()

    async with dp_uow_provider.get_data_plane_uow(tenant_id, shard_id, shard_dsn) as uow:
        service = MeterReadingInspectionService(
            olap_client=olap_client,
            manifest_repo=uow.batch_manifests,
        )
        sample_dto = await service.get_micro_sample(
            batch_id=batch_id,
            tenant_id=tenant_id,
            limit=limit,
            offset=offset,
        )

        sample_list: list[dict[str, object]] = []
        for r in sample_dto.micro_sample_records:
            sample_list.append(dict(r))

        return BatchReadingSampleHttpResponse(
            batch_id=sample_dto.batch_id,
            tenant_id=sample_dto.tenant_id,
            total_count=sample_dto.total_count,
            valid_count=sample_dto.valid_count,
            quarantined_count=sample_dto.quarantined_count,
            window_start_utc=sample_dto.window_start_utc,
            window_end_utc=sample_dto.window_end_utc,
            micro_sample_records=sample_list,
        )
