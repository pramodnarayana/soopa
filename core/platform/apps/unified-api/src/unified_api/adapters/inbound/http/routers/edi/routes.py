from typing import Any

from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyControlPlaneUnitOfWork as ControlPlaneUnitOfWork,
)
from edi.application.dtos import (
    UNSET,
    CreateInboundRouteCmd,
    CreateOutboundRouteCmd,
    UpdateInboundRouteCmd,
    UpdateOutboundRouteCmd,
)
from edi.application.use_cases.inbound_routes.create_inbound_route_use_case import (
    CreateInboundRouteUseCase,
)
from edi.application.use_cases.inbound_routes.delete_inbound_route_use_case import (
    DeleteInboundRouteUseCase,
)
from edi.application.use_cases.inbound_routes.list_inbound_routes_use_case import (
    ListInboundRoutesUseCase,
)
from edi.application.use_cases.inbound_routes.update_inbound_route_use_case import (
    UpdateInboundRouteUseCase,
)
from edi.application.use_cases.outbound_routes import (
    CreateOutboundRouteUseCase,
    DeleteOutboundRouteUseCase,
    ListOutboundRoutesUseCase,
    UpdateOutboundRouteUseCase,
)
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import TypeAdapter

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.headers import get_idempotency_key
from unified_api.adapters.inbound.http.dtos.edi.dtos import (
    CreateInboundRouteRequest,
    CreateOutboundRouteRequest,
    RouteItemResponse,
    RouteResponse,
    UpdateRouteRequest,
)

router = APIRouter(prefix="/api/v1/tenants/{tenant_id}/edi/routes", tags=["Routes"])

# Built once at import time — TypeAdapter construction is not free.
_route_list_adapter = TypeAdapter(list[RouteItemResponse])


@router.get("", response_model=list[RouteItemResponse], status_code=status.HTTP_200_OK)
async def list_routes(
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """
    List all Active Routes for the current Tenant.
    """
    async with uow:
        inbound_service = ListInboundRoutesUseCase(uow=uow)
        outbound_use_case = ListOutboundRoutesUseCase(uow=uow)

        inbound_routes = await inbound_service.list_inbound_routes(tenant_id)
        outbound_routes = await outbound_use_case.execute(tenant_id)

        routes = inbound_routes + outbound_routes
        return _route_list_adapter.validate_python(routes)


@router.post("/inbound", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_inbound_route(
    request: CreateInboundRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """
    Creates a new Inbound Route directly in the Tenant Data Plane.
    """
    async with uow:
        service = CreateInboundRouteUseCase(uow=uow)

        cmd = CreateInboundRouteCmd(
            trading_partner_id=request.trading_partner_id,
            isa_sender_id=request.isa_sender_id,
            isa_receiver_id=request.isa_receiver_id,
            gs_sender_id=request.gs_sender_id,
            gs_receiver_id=request.gs_receiver_id,
            transaction_type=request.transaction_type,
            processing_mode=request.processing_mode,
            webhook_id=request.webhook_id,
            as2_partner_id=request.as2_partner_id if request.as2_partner_id else None,
            sftp_partner_id=request.sftp_partner_id if request.sftp_partner_id else None,
        )

        entity = await service.create_inbound_route(tenant_id, cmd, idempotency_key=idempotency_key)
        await uow.commit()

        return RouteResponse(route_id=entity.id, tenant_id=entity.tenant_id, direction="INBOUND")


@router.post("/outbound", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_outbound_route(
    request: CreateOutboundRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """
    Creates a new Outbound Route directly in the Tenant Data Plane.
    """
    async with uow:
        use_case = CreateOutboundRouteUseCase(uow=uow)

        cmd = CreateOutboundRouteCmd(
            isa_sender_id=request.isa_sender_id if hasattr(request, "isa_sender_id") else "",
            isa_receiver_id=request.isa_receiver_id if hasattr(request, "isa_receiver_id") else "",
            transaction_type=request.transaction_type
            if hasattr(request, "transaction_type")
            else "",
            trading_partner_id=request.trading_partner_id,
            as2_partner_id=request.as2_partner_id if request.as2_partner_id else None,
            sftp_partner_id=request.sftp_partner_id if request.sftp_partner_id else None,
        )

        entity = await use_case.execute(tenant_id, cmd, idempotency_key=idempotency_key)
        await uow.commit()

        return RouteResponse(route_id=entity.id, tenant_id=entity.tenant_id, direction="OUTBOUND")


@router.patch("/inbound/{route_id}", status_code=status.HTTP_200_OK)
async def update_inbound_route(
    route_id: str,
    request: UpdateRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """
    Updates an Inbound Route for the current Tenant.
    """
    async with uow:
        service = UpdateInboundRouteUseCase(uow=uow)

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

        success = await service.update_inbound_route(
            tenant_id, route_id, cmd, idempotency_key=idempotency_key
        )
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()
    return {"status": "ok"}


@router.delete("/inbound/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inbound_route(
    route_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> None:
    """
    Deletes an Inbound Route for the current Tenant.
    """
    async with uow:
        service = DeleteInboundRouteUseCase(uow=uow)
        success = await service.delete_inbound_route(
            tenant_id, route_id, idempotency_key=idempotency_key
        )
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()


@router.patch("/outbound/{route_id}", status_code=status.HTTP_200_OK)
async def update_outbound_route(
    route_id: str,
    request: UpdateRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> Any:
    """
    Updates an Outbound Route for the current Tenant.
    """
    async with uow:
        use_case = UpdateOutboundRouteUseCase(uow=uow)

        dump = request.model_dump(exclude_unset=True)
        cmd = UpdateOutboundRouteCmd(
            trading_partner_id=dump.get("trading_partner_id", UNSET),
            name=dump.get("name", UNSET),
            as2_partner_id=dump.get("as2_partner_id", UNSET),
            sftp_partner_id=dump.get("sftp_partner_id", UNSET),
            active=dump.get("active", UNSET),
        )

        success = await use_case.execute(tenant_id, route_id, cmd, idempotency_key=idempotency_key)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()
    return {"status": "ok"}


@router.delete("/outbound/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outbound_route(
    route_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWork = Depends(get_control_plane_uow),
) -> None:
    """
    Deletes an Outbound Route for the current Tenant.
    """
    async with uow:
        use_case = DeleteOutboundRouteUseCase(uow=uow)
        success = await use_case.execute(tenant_id, route_id, idempotency_key=idempotency_key)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()
