from typing import Any

from edi.application.use_cases.inbound_routes.create_inbound_route_use_case import (
    CreateInboundRouteCmd,
    CreateInboundRouteUseCase,
)
from edi.application.use_cases.inbound_routes.delete_inbound_route_use_case import (
    DeleteInboundRouteUseCase,
)
from edi.application.use_cases.inbound_routes.list_inbound_routes_use_case import (
    ListInboundRoutesUseCase,
)
from edi.application.use_cases.inbound_routes.update_inbound_route_use_case import (
    UpdateInboundRouteCmd,
    UpdateInboundRouteUseCase,
)
from edi.domain.models.inbound_routes import InboundRouteDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, HTTPException, status
from seedwork.domain.types import UNSET

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.headers import get_idempotency_key
from unified_api.adapters.inbound.http.edi.dtos.dtos import (
    CreateInboundRouteRequest,
    InboundRouteItem,
    RouteResponse,
    UpdateRouteRequest,
)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/edi/inbound-routes",
    tags=["Inbound Routes"],
)

_PROTOCOL_DESTINATION_MAP = {
    "Webhook": "Webhook",
    "OpenAS2": "OpenAS2",
    "AS2": "OpenAS2",
    "SFTP": "SFTP",
    "API": "API",
}


def _to_dto(domain: InboundRouteDomainModel) -> dict[str, Any]:
    dest_type = "Unknown"
    if domain.connection_type:
        dest_type = _PROTOCOL_DESTINATION_MAP.get(
            domain.connection_type.value, domain.connection_type.value
        )

    return {
        "route_id": domain.id,
        "tenant_id": domain.tenant_id,
        "name": domain.name or "",
        "destination_type": dest_type,
        "destination_name": "",
        "trading_partner_id": domain.trading_partner_id,
        "webhook_id": domain.webhook_id,
        "as2_partner_id": domain.as2_partner_id,
        "sftp_partner_id": domain.sftp_partner_id,
        "active": domain.active,
        "isa_sender_id": domain.isa_sender_id,
        "isa_receiver_id": domain.isa_receiver_id,
        "gs_sender_id": domain.gs_sender_id,
        "gs_receiver_id": domain.gs_receiver_id,
        "transaction_type": domain.transaction_type or "*",
        "processing_mode": (
            domain.processing_mode.value
            if hasattr(domain.processing_mode, "value")
            else str(domain.processing_mode)
        )
        if domain.processing_mode
        else "TRANSFORM",
    }


@router.get("", response_model=list[InboundRouteItem], status_code=status.HTTP_200_OK)
async def list_inbound_routes(
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> list[InboundRouteItem]:
    """
    List all Inbound Routes for the current Tenant.
    """
    async with uow:
        use_case = ListInboundRoutesUseCase(uow=uow)
        routes = await use_case.list_inbound_routes(tenant_id)
        return [InboundRouteItem.model_validate(_to_dto(r)) for r in routes]


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_inbound_route(
    request: CreateInboundRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> RouteResponse:
    """
    Creates a new Inbound Route for the current Tenant.
    """
    async with uow:
        use_case = CreateInboundRouteUseCase(uow=uow)

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
            as2_partner_id=request.as2_partner_id if request.as2_partner_id else None,
            sftp_partner_id=request.sftp_partner_id if request.sftp_partner_id else None,
        )

        entity = await use_case.create_inbound_route(
            tenant_id, cmd, idempotency_key=idempotency_key
        )
        await uow.commit()

        return RouteResponse(route_id=entity.id, tenant_id=entity.tenant_id, direction="INBOUND")


@router.patch("/{route_id}", status_code=status.HTTP_200_OK)
async def update_inbound_route(
    route_id: str,
    request: UpdateRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> dict[str, str]:
    """
    Updates an Inbound Route for the current Tenant.
    """
    async with uow:
        use_case = UpdateInboundRouteUseCase(uow=uow)

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

        success = await use_case.update_inbound_route(
            tenant_id, route_id, cmd, idempotency_key=idempotency_key
        )
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()
    return {"status": "ok"}


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inbound_route(
    route_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> None:
    """
    Deletes an Inbound Route for the current Tenant.
    """
    async with uow:
        use_case = DeleteInboundRouteUseCase(uow=uow)
        success = await use_case.delete_inbound_route(
            tenant_id, route_id, idempotency_key=idempotency_key
        )
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")
        await uow.commit()
