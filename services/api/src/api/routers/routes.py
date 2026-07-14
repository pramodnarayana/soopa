from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from identity.dependencies import get_current_tenant_id
from pydantic import TypeAdapter

from api.adapters.http.dtos import (
    CreateInboundRouteRequest,
    CreateOutboundRouteRequest,
    RouteItemResponse,
    RouteResponse,
    UpdateRouteRequest,
)
from api.core.services import RouteService
from api.core.uow import UnitOfWork
from api.dependencies import get_tenant_uow
from api.domain.models import (
    UNSET,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    UpdateInboundRouteCmd,
    UpdateOutboundRouteCmd,
)

router = APIRouter(prefix="/api/v1/routes", tags=["Routes"])

# Built once at import time — TypeAdapter construction is not free.
_route_list_adapter = TypeAdapter(list[RouteItemResponse])


@router.get("", response_model=list[RouteItemResponse], status_code=status.HTTP_200_OK)
async def list_routes(
    tenant_id: int = Depends(get_current_tenant_id),
    uow: UnitOfWork = Depends(get_tenant_uow),
) -> Any:
    """
    List all Active Routes for the current Tenant.
    """
    async with uow:
        service = RouteService(global_repo=uow.control_plane)
        routes = await service.list_routes(tenant_id)
        return _route_list_adapter.validate_python(routes)


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
        service = RouteService(global_repo=uow.control_plane)

        cmd = CreateInboundRouteCmd(
            name=request.name,
            trading_partner_id=request.trading_partner_id,
            isa_sender_id=request.isa_sender_id,
            isa_receiver_id=request.isa_receiver_id,
            gs_sender_id=request.gs_sender_id,
            gs_receiver_id=request.gs_receiver_id,
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
        service = RouteService(global_repo=uow.control_plane)

        cmd = CreateOutboundRouteCmd(
            trading_partner_id=request.trading_partner_id,
            name=request.name,
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
    """
    Updates an Inbound Route for the current Tenant.
    """
    async with uow:
        service = RouteService(global_repo=uow.control_plane)

        dump = request.model_dump(exclude_unset=True)
        cmd = UpdateInboundRouteCmd(
            name=dump.get("name", UNSET),
            trading_partner_id=dump.get("trading_partner_id", UNSET),
            isa_sender_id=dump.get("isa_sender_id", UNSET),
            isa_receiver_id=dump.get("isa_receiver_id", UNSET),
            gs_sender_id=dump.get("gs_sender_id", UNSET),
            gs_receiver_id=dump.get("gs_receiver_id", UNSET),
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
    """
    Deletes an Inbound Route for the current Tenant.
    """
    async with uow:
        service = RouteService(global_repo=uow.control_plane)
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
    """
    Updates an Outbound Route for the current Tenant.
    """
    async with uow:
        service = RouteService(global_repo=uow.control_plane)

        dump = request.model_dump(exclude_unset=True)
        cmd = UpdateOutboundRouteCmd(
            trading_partner_id=dump.get("trading_partner_id", UNSET),
            name=dump.get("name", UNSET),
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
    """
    Deletes an Outbound Route for the current Tenant.
    """
    async with uow:
        service = RouteService(global_repo=uow.control_plane)
        success = await service.delete_outbound_route(tenant_id, route_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()
