from typing import Any

from fastapi import APIRouter, Depends, status
from identity.dependencies import get_current_tenant_id

from api.adapters.http.dtos import (
    CreateInboundRouteRequest,
    CreateOutboundRouteRequest,
    RouteItemResponse,
    RouteResponse,
)
from api.core.provisioning import ProvisioningService
from api.core.uow import UnitOfWork
from api.dependencies import get_tenant_uow
from api.domain.models import (
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
)

router = APIRouter(prefix="/api/v1/routes", tags=["Routes"])


@router.get("", response_model=list[RouteItemResponse], status_code=status.HTTP_200_OK)
async def list_routes(
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """
    List all Active Routes for the current Tenant.
    """
    async with uow:
        from typing import cast

        from api.ports.repository import DataPlaneRepositoryPort

        data_plane = cast(DataPlaneRepositoryPort, uow.data_plane)
        service = ProvisioningService(uow.control_plane, data_plane)
        routes = await service.list_routes()

        return [RouteItemResponse(**r) for r in routes]


@router.post("/inbound", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_inbound_route(
    request: CreateInboundRouteRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """
    Creates a new Inbound Route directly in the Tenant Data Plane.
    """
    async with uow:
        service = ProvisioningService(None, uow.data_plane)  # type: ignore

        cmd = CreateInboundRouteCmd(
            isa_sender_id=request.isa_sender_id,
            isa_receiver_id=request.isa_receiver_id,
            transaction_type=request.transaction_type,
            webhook_partner_id=request.webhook_partner_id,
            as2_partner_id=request.as2_partner_id,
            sftp_partner_id=request.sftp_partner_id,
        )

        entity = await service.create_inbound_route(tenant_id, cmd)
        await uow.commit()

        return RouteResponse(
            route_id=entity.route_id, tenant_id=entity.tenant_id, direction=entity.direction
        )


@router.post("/outbound", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_outbound_route(
    request: CreateOutboundRouteRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """
    Creates a new Outbound Route directly in the Tenant Data Plane.
    """
    async with uow:
        service = ProvisioningService(None, uow.data_plane)  # type: ignore

        cmd = CreateOutboundRouteCmd(
            isa_sender_id=request.isa_sender_id,
            isa_receiver_id=request.isa_receiver_id,
            transaction_type=request.transaction_type,
            as2_partner_id=request.as2_partner_id,
            sftp_partner_id=request.sftp_partner_id,
        )

        entity = await service.create_outbound_route(tenant_id, cmd)
        await uow.commit()

        return RouteResponse(
            route_id=entity.route_id, tenant_id=entity.tenant_id, direction=entity.direction
        )
