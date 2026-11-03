from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, UnsetType

from edi.domain.exceptions import EdiError, RouteNotFoundEdiError
from edi.domain.routing.enums import EdiConnectionType, EdiDirection
from edi.domain.routing.outbound_route import OutboundRoute
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class UpdateOutboundRouteCmd:
    as2_partner_id: str | UnsetType | None = UNSET
    sftp_partner_id: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET
    name: str | UnsetType | None = UNSET
    connection_type: EdiConnectionType | UnsetType | None = UNSET
    trading_partner_id: str | UnsetType | None = UNSET


class UpdateOutboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        route_id: str,
        cmd: UpdateOutboundRouteCmd,
        idempotency_key: str | None = None,
    ) -> Result[OutboundRoute, EdiError]:
        aggregate = await self.uow.outbound_routes.get_outbound_route(tenant_id, route_id)
        if not aggregate:
            not_found = RouteNotFoundEdiError.for_id(
                route_id, direction=EdiDirection.OUTBOUND.value
            )
            logger.error(
                "outbound_route_update_not_found",
                route_id=route_id,
                tenant_id=tenant_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

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
            name=cmd.name,
            trading_partner_id=cmd.trading_partner_id,
            as2_partner_id=as2,
            sftp_partner_id=sftp,
            connection_type=cmd.connection_type,
            active=cmd.active,
            idempotency_key=idempotency_key,
        )
        if upd_res.is_err:
            domain_err = upd_res.unwrap_err()
            logger.error(
                "outbound_route_update_validation_failed",
                route_id=route_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        await self.uow.outbound_routes.save(aggregate)

        logger.info(
            "outbound_route_updated",
            route_id=route_id,
            tenant_id=tenant_id,
        )

        return Result.ok(aggregate)
