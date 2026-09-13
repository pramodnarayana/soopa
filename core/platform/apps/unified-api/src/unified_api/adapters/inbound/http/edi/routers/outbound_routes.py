from typing import Any

from edi.application.use_cases.outbound_routes import (
    CreateOutboundRouteCmd,
    CreateOutboundRouteUseCase,
    DeleteOutboundRouteUseCase,
    ListOutboundRoutesUseCase,
    UpdateOutboundRouteCmd,
    UpdateOutboundRouteUseCase,
)
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, HTTPException, status
from seedwork.domain.types import UNSET

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.headers import get_idempotency_key
from unified_api.adapters.inbound.http.edi.dtos.dtos import (
    CreateOutboundRouteRequest,
    OutboundRouteItem,
    RouteResponse,
    UpdateRouteRequest,
)

router = APIRouter(
    prefix="/api/v1/tenants/{tenant_id}/edi/outbound-routes",
    tags=["Outbound Routes"],
)

_PROTOCOL_DESTINATION_MAP = {
    "Webhook": "Webhook",
    "OpenAS2": "OpenAS2",
    "AS2": "OpenAS2",
    "SFTP": "SFTP",
    "API": "API",
}


def _to_dto(domain: OutboundRouteDomainModel) -> dict[str, Any]:
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
        "as2_partner_id": domain.as2_partner_id,
        "sftp_partner_id": domain.sftp_partner_id,
        "active": domain.active,
    }


@router.get("", response_model=list[OutboundRouteItem], status_code=status.HTTP_200_OK)
async def list_outbound_routes(
    limit: int = 100,
    offset: int = 0,
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> list[OutboundRouteItem]:
    """
    List all Outbound Routes for the current Tenant.
    """
    async with uow:
        use_case = ListOutboundRoutesUseCase(uow=uow)
        routes = await use_case.execute(tenant_id, limit, offset)
        return [OutboundRouteItem.model_validate(_to_dto(r)) for r in routes]


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_outbound_route(
    request: CreateOutboundRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> RouteResponse:
    """
    Creates a new Outbound Route for the current Tenant.
    """
    async with uow:
        use_case = CreateOutboundRouteUseCase(uow=uow)

        cmd = CreateOutboundRouteCmd(
            isa_sender_id="",
            isa_receiver_id="",
            transaction_type="*",
            name=request.name,
            trading_partner_id=request.trading_partner_id,
            as2_partner_id=request.as2_partner_id if request.as2_partner_id else None,
            sftp_partner_id=request.sftp_partner_id if request.sftp_partner_id else None,
        )

        entity = await use_case.execute(tenant_id, cmd, idempotency_key=idempotency_key)
        await uow.commit()

        return RouteResponse(route_id=entity.id, tenant_id=entity.tenant_id, direction="OUTBOUND")


@router.patch("/{route_id}", status_code=status.HTTP_200_OK)
async def update_outbound_route(
    route_id: str,
    request: UpdateRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> dict[str, str]:
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


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outbound_route(
    route_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
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
