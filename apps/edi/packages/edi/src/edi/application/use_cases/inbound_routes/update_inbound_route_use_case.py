"""Update Inbound Route Use Case."""

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, UnsetType

from edi.domain.exceptions import EdiError, EdiValidationError, RouteNotFoundEdiError
from edi.domain.routing.enums import EdiConnectionType, EdiDirection, ProcessingMode
from edi.domain.routing.inbound_route import InboundRoute
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UpdateInboundRouteCmd:
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    transaction_type: str | UnsetType | None = UNSET
    webhook_id: str | UnsetType | None = UNSET
    as2_partner_id: str | UnsetType | None = UNSET
    sftp_partner_id: str | UnsetType | None = UNSET
    connection_type: EdiConnectionType | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET
    name: str | UnsetType | None = UNSET
    trading_partner_id: str | UnsetType | None = UNSET
    gs_sender_id: str | UnsetType | None = UNSET
    gs_receiver_id: str | UnsetType | None = UNSET
    processing_mode: str | UnsetType | None = UNSET


class UpdateInboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_inbound_route(
        self,
        tenant_id: str,
        route_id: str,
        cmd: UpdateInboundRouteCmd,
        idempotency_key: str | None = None,
    ) -> Result[InboundRoute, EdiError]:
        aggregate: InboundRoute | None = await self.uow.inbound_routes.get_inbound_route_by_id(
            tenant_id, route_id
        )
        if not aggregate:
            not_found = RouteNotFoundEdiError.for_id(route_id, direction=EdiDirection.INBOUND.value)
            logger.error(
                "inbound_route_update_not_found",
                route_id=route_id,
                tenant_id=tenant_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

        mode: ProcessingMode | UnsetType | None = UNSET
        if not isinstance(cmd.processing_mode, UnsetType):
            if cmd.processing_mode:
                try:
                    mode = ProcessingMode(cmd.processing_mode)
                except ValueError:
                    bad_mode = EdiValidationError.with_message(
                        f"Invalid processing_mode '{cmd.processing_mode}'.",
                        details={"processing_mode": cmd.processing_mode},
                    )
                    logger.error(
                        "inbound_route_update_invalid_processing_mode",
                        route_id=route_id,
                        processing_mode=cmd.processing_mode,
                        tenant_id=tenant_id,
                        error_code=bad_mode.code,
                    )
                    return Result.fail(bad_mode)
            else:
                mode = None

        wh: str | UnsetType | None = (
            (str(cmd.webhook_id) if cmd.webhook_id else None)
            if not isinstance(cmd.webhook_id, UnsetType)
            else UNSET
        )
        as2: str | UnsetType | None = (
            (str(cmd.as2_partner_id) if cmd.as2_partner_id else None)
            if not isinstance(cmd.as2_partner_id, UnsetType)
            else UNSET
        )
        sftp: str | UnsetType | None = (
            (str(cmd.sftp_partner_id) if cmd.sftp_partner_id else None)
            if not isinstance(cmd.sftp_partner_id, UnsetType)
            else UNSET
        )

        upd_res = aggregate.update(
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            gs_sender_id=cmd.gs_sender_id,
            gs_receiver_id=cmd.gs_receiver_id,
            transaction_type=cmd.transaction_type,
            processing_mode=mode,
            name=cmd.name,
            trading_partner_id=cmd.trading_partner_id,
            webhook_id=wh,
            as2_partner_id=as2,
            sftp_partner_id=sftp,
            connection_type=cmd.connection_type,
            active=cmd.active,
            idempotency_key=idempotency_key,
        )
        if upd_res.is_err:
            domain_err = upd_res.unwrap_err()
            logger.error(
                "inbound_route_update_validation_failed",
                route_id=route_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        await self.uow.inbound_routes.save(aggregate)

        logger.info(
            "inbound_route_updated",
            route_id=route_id,
            tenant_id=tenant_id,
        )
        return Result.ok(aggregate)
