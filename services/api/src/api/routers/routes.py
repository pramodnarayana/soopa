from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from identity.dependencies import get_current_tenant_id

from api.adapters.http.dtos import (
    CreateInboundRouteRequest,
    CreateOutboundRouteRequest,
    RouteItemResponse,
    RouteResponse,
    UpdateRouteRequest,
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
        service = ProvisioningService(tenant_repo=data_plane, global_repo=uow.control_plane)
        routes = await service.list_routes(tenant_id)

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
        service = ProvisioningService(tenant_repo=uow.data_plane, global_repo=uow.control_plane)

        cmd = CreateInboundRouteCmd(
            name=request.name,
            isa_sender_id=request.isa_sender_id,
            isa_receiver_id=request.isa_receiver_id,
            transaction_type=request.transaction_type,
            processing_mode=request.processing_mode,
            webhook_id=request.webhook_id,
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
        service = ProvisioningService(tenant_repo=uow.data_plane, global_repo=uow.control_plane)

        cmd = CreateOutboundRouteCmd(
            name=request.name,
            isa_sender_id=request.isa_sender_id,
            isa_receiver_id=request.isa_receiver_id,
            transaction_type=request.transaction_type,
            processing_mode=request.processing_mode,
            as2_partner_id=request.as2_partner_id,
            sftp_partner_id=request.sftp_partner_id,
        )

        entity = await service.create_outbound_route(tenant_id, cmd)
        await uow.commit()

        return RouteResponse(
            route_id=entity.route_id, tenant_id=entity.tenant_id, direction=entity.direction
        )


@router.patch("/inbound/{route_id}", status_code=status.HTTP_200_OK)
async def update_inbound_route(
    route_id: UUID,
    request: UpdateRouteRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane, global_repo=uow.control_plane)
        from api.domain.models import UNSET, UpdateInboundRouteCmd

        dump = request.model_dump(exclude_unset=True)
        cmd = UpdateInboundRouteCmd(
            name=dump.get("name", UNSET),
            isa_sender_id=dump.get("isa_sender_id", UNSET),
            isa_receiver_id=dump.get("isa_receiver_id", UNSET),
            transaction_type=dump.get("transaction_type", UNSET),
            processing_mode=dump.get("processing_mode", UNSET),
            webhook_id=dump.get("webhook_id", UNSET),
            as2_partner_id=dump.get("as2_partner_id", UNSET),
            sftp_partner_id=dump.get("sftp_partner_id", UNSET),
            active=dump.get("active", UNSET),
        )

        success = await service.update_inbound_route(tenant_id, route_id, cmd)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()
    return {"status": "ok"}


@router.delete("/inbound/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inbound_route(
    route_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> None:
    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane, global_repo=uow.control_plane)
        success = await service.delete_inbound_route(tenant_id, route_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()


@router.patch("/outbound/{route_id}", status_code=status.HTTP_200_OK)
async def update_outbound_route(
    route_id: UUID,
    request: UpdateRouteRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane, global_repo=uow.control_plane)
        from api.domain.models import UNSET, UpdateOutboundRouteCmd

        dump = request.model_dump(exclude_unset=True)
        cmd = UpdateOutboundRouteCmd(
            name=dump.get("name", UNSET),
            isa_sender_id=dump.get("isa_sender_id", UNSET),
            isa_receiver_id=dump.get("isa_receiver_id", UNSET),
            transaction_type=dump.get("transaction_type", UNSET),
            processing_mode=dump.get("processing_mode", UNSET),
            as2_partner_id=dump.get("as2_partner_id", UNSET),
            sftp_partner_id=dump.get("sftp_partner_id", UNSET),
            active=dump.get("active", UNSET),
        )

        success = await service.update_outbound_route(tenant_id, route_id, cmd)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()
    return {"status": "ok"}


@router.delete("/outbound/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outbound_route(
    route_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> None:
    async with uow:
        service = ProvisioningService(tenant_repo=uow.data_plane, global_repo=uow.control_plane)
        success = await service.delete_outbound_route(tenant_id, route_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()
