from edi.application.use_cases.outbound_routes import (
    CreateOutboundRouteCmd,
    CreateOutboundRouteUseCase,
    DeleteOutboundRouteUseCase,
    ListOutboundRoutesUseCase,
    UpdateOutboundRouteCmd,
    UpdateOutboundRouteUseCase,
)
from edi.domain.routing.constants import WILDCARD_TRANSACTION_TYPE
from edi.domain.routing.enums import EdiDirection
from edi.domain.routing.outbound_route import OutboundRoute
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, status
from outbox.ports.outbox_publisher_port import OutboxPublisherPort
from seedwork.domain.types import UNSET

from unified_api.adapters.inbound.http.dependencies.edi.auth import get_current_tenant_id
from unified_api.adapters.inbound.http.dependencies.edi.database import get_control_plane_uow
from unified_api.adapters.inbound.http.dependencies.edi.headers import get_idempotency_key
from unified_api.adapters.inbound.http.dependencies.edi.services import get_outbox_publisher
from unified_api.adapters.inbound.http.edi.dtos.dtos import (
    CreateOutboundRouteRequest,
    OutboundRouteItem,
    RouteResponse,
    UpdateRouteRequest,
)
from unified_api.adapters.inbound.http.edi.error_mapper import raise_http_for_edi_error

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


def _to_item(domain: OutboundRoute) -> OutboundRouteItem:
    dest_type = "Unknown"
    if domain.connection_type:
        dest_type = _PROTOCOL_DESTINATION_MAP.get(
            domain.connection_type.value, domain.connection_type.value
        )

    return OutboundRouteItem(
        route_id=domain.id,
        name=domain.name or "",
        destination_type=dest_type,
        destination_name="",
        trading_partner_id=domain.trading_partner_id,
        as2_partner_id=domain.as2_partner_id,
        sftp_partner_id=domain.sftp_partner_id,
        active=domain.active,
    )


@router.get("", response_model=list[OutboundRouteItem], status_code=status.HTTP_200_OK)
async def list_outbound_routes(
    limit: int = 100,
    offset: int = 0,
    tenant_id: str = Depends(get_current_tenant_id),
    publisher: OutboxPublisherPort = Depends(get_outbox_publisher),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> list[OutboundRouteItem]:
    """List all Outbound Routes for the current Tenant."""
    async with uow:
        use_case = ListOutboundRoutesUseCase(uow=uow)
        routes = await use_case.execute(tenant_id, limit, offset)
        return [_to_item(r) for r in routes]


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_outbound_route(
    request: CreateOutboundRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    publisher: OutboxPublisherPort = Depends(get_outbox_publisher),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> RouteResponse:
    """Creates a new Outbound Route for the current Tenant."""
    async with uow:
        use_case = CreateOutboundRouteUseCase(uow=uow)

        cmd = CreateOutboundRouteCmd(
            isa_sender_id="",
            isa_receiver_id="",
            transaction_type=WILDCARD_TRANSACTION_TYPE,
            name=request.name,
            trading_partner_id=request.trading_partner_id,
            as2_partner_id=request.as2_partner_id if request.as2_partner_id else None,
            sftp_partner_id=request.sftp_partner_id if request.sftp_partner_id else None,
        )

        create_res = await use_case.execute(tenant_id, cmd, idempotency_key=idempotency_key)
        if create_res.is_err:
            raise_http_for_edi_error(create_res.unwrap_err())
        entity = create_res.unwrap()
        await uow.commit()

        return RouteResponse(
            route_id=entity.id,
            tenant_id=entity.tenant_id,
            direction=EdiDirection.OUTBOUND.value,
        )


@router.patch("/{route_id}", status_code=status.HTTP_200_OK)
async def update_outbound_route(
    route_id: str,
    request: UpdateRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    publisher: OutboxPublisherPort = Depends(get_outbox_publisher),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> dict[str, str]:
    """Updates an Outbound Route for the current Tenant."""
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

        upd_res = await use_case.execute(tenant_id, route_id, cmd, idempotency_key=idempotency_key)
        if upd_res.is_err:
            raise_http_for_edi_error(upd_res.unwrap_err())
        await uow.commit()
    return {"status": "ok"}


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outbound_route(
    route_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    publisher: OutboxPublisherPort = Depends(get_outbox_publisher),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> None:
    """Deletes an Outbound Route for the current Tenant."""
    async with uow:
        use_case = DeleteOutboundRouteUseCase(uow=uow)
        del_res = await use_case.execute(tenant_id, route_id, idempotency_key=idempotency_key)
        if del_res.is_err:
            raise_http_for_edi_error(del_res.unwrap_err())
        await uow.commit()
