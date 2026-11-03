from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from edi.domain.exceptions import EdiError
from edi.domain.routing.enums import EdiConnectionType
from edi.domain.routing.outbound_route import OutboundRoute
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateOutboundRouteCmd:
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    name: str | None = None
    connection_type: EdiConnectionType | None = None
    trading_partner_id: str | None = None


class CreateOutboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, cmd: CreateOutboundRouteCmd, idempotency_key: str | None = None
    ) -> Result[OutboundRoute, EdiError]:
        logger.info(
            "creating_outbound_route",
            trading_partner_id=cmd.trading_partner_id,
            tenant_id=tenant_id,
        )

        create_res = OutboundRoute.create(
            tenant_id=tenant_id,
            trading_partner_id=cmd.trading_partner_id,
            name=cmd.name,
            as2_partner_id=str(cmd.as2_partner_id) if cmd.as2_partner_id else None,
            sftp_partner_id=str(cmd.sftp_partner_id) if cmd.sftp_partner_id else None,
            connection_type=cmd.connection_type,
            idempotency_key=idempotency_key,
        )
        if create_res.is_err:
            domain_err = create_res.unwrap_err()
            logger.error(
                "outbound_route_create_validation_failed",
                trading_partner_id=cmd.trading_partner_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        aggregate = create_res.unwrap()
        await self.uow.outbound_routes.save(aggregate)

        logger.info(
            "outbound_route_created",
            route_id=aggregate.id,
            tenant_id=tenant_id,
        )
        return Result.ok(aggregate)
