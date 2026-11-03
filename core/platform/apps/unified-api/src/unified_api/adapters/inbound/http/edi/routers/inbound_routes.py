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
from edi.domain.routing.constants import WILDCARD_TRANSACTION_TYPE
from edi.domain.routing.enums import EdiDirection, ProcessingMode
from edi.domain.routing.inbound_route import InboundRoute
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort
from fastapi import APIRouter, Depends, status
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
from unified_api.adapters.inbound.http.edi.error_mapper import raise_http_for_edi_error

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


def _to_item(domain: InboundRoute) -> InboundRouteItem:
    dest_type = "Unknown"
    if domain.connection_type:
        dest_type = _PROTOCOL_DESTINATION_MAP.get(
            domain.connection_type.value, domain.connection_type.value
        )

    return InboundRouteItem(
        route_id=domain.id,
        name=domain.name or "",
        destination_type=dest_type,
        destination_name="",
        trading_partner_id=domain.trading_partner_id,
        webhook_id=domain.webhook_id,
        as2_partner_id=domain.as2_partner_id,
        sftp_partner_id=domain.sftp_partner_id,
        active=domain.active,
        isa_sender_id=domain.isa_sender_id,
        isa_receiver_id=domain.isa_receiver_id,
        gs_sender_id=domain.gs_sender_id,
        gs_receiver_id=domain.gs_receiver_id,
        transaction_type=domain.transaction_type or WILDCARD_TRANSACTION_TYPE,
        processing_mode=domain.processing_mode.value
        if domain.processing_mode
        else ProcessingMode.TRANSFORM.value,
    )


@router.get("", response_model=list[InboundRouteItem], status_code=status.HTTP_200_OK)
async def list_inbound_routes(
    tenant_id: str = Depends(get_current_tenant_id),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> list[InboundRouteItem]:
    """List all Inbound Routes for the current Tenant."""
    async with uow:
        use_case = ListInboundRoutesUseCase(uow=uow)
        routes = await use_case.list_inbound_routes(tenant_id)
        return [_to_item(r) for r in routes]


@router.post("", response_model=RouteResponse, status_code=status.HTTP_201_CREATED)
async def create_inbound_route(
    request: CreateInboundRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> RouteResponse:
    """Creates a new Inbound Route for the current Tenant."""
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

        create_res = await use_case.create_inbound_route(
            tenant_id, cmd, idempotency_key=idempotency_key
        )
        if create_res.is_err:
            raise_http_for_edi_error(create_res.unwrap_err())
        entity = create_res.unwrap()
        await uow.commit()

        return RouteResponse(
            route_id=entity.id,
            tenant_id=entity.tenant_id,
            direction=EdiDirection.INBOUND.value,
        )


@router.patch("/{route_id}", status_code=status.HTTP_200_OK)
async def update_inbound_route(
    route_id: str,
    request: UpdateRouteRequest,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> dict[str, str]:
    """Updates an Inbound Route for the current Tenant."""
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

        upd_res = await use_case.update_inbound_route(
            tenant_id, route_id, cmd, idempotency_key=idempotency_key
        )
        if upd_res.is_err:
            raise_http_for_edi_error(upd_res.unwrap_err())
        await uow.commit()
    return {"status": "ok"}


@router.delete("/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inbound_route(
    route_id: str,
    tenant_id: str = Depends(get_current_tenant_id),
    idempotency_key: str | None = Depends(get_idempotency_key),
    uow: ControlPlaneUnitOfWorkPort = Depends(get_control_plane_uow),
) -> None:
    """Deletes an Inbound Route for the current Tenant."""
    async with uow:
        use_case = DeleteInboundRouteUseCase(uow=uow)
        del_res = await use_case.delete_inbound_route(
            tenant_id, route_id, idempotency_key=idempotency_key
        )
        if del_res.is_err:
            raise_http_for_edi_error(del_res.unwrap_err())
        await uow.commit()
