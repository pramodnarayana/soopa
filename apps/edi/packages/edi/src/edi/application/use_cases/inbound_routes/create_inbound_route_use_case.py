from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from edi.domain.exceptions import EdiError, EdiValidationError
from edi.domain.routing.enums import EdiConnectionType, ProcessingMode
from edi.domain.routing.inbound_route import InboundRoute
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateInboundRouteCmd:
    isa_sender_id: str
    isa_receiver_id: str
    transaction_type: str
    webhook_id: str | None = None
    as2_partner_id: str | None = None
    sftp_partner_id: str | None = None
    connection_type: EdiConnectionType | None = None
    name: str | None = None
    trading_partner_id: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    processing_mode: str | None = None


class CreateInboundRouteUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_inbound_route(
        self, tenant_id: str, cmd: CreateInboundRouteCmd, idempotency_key: str | None = None
    ) -> Result[InboundRoute, EdiError]:
        logger.info(
            "creating_inbound_route",
            isa_sender_id=cmd.isa_sender_id,
            tenant_id=tenant_id,
        )

        mode: ProcessingMode | None = None
        if cmd.processing_mode:
            try:
                mode = ProcessingMode(cmd.processing_mode)
            except ValueError:
                bad_mode = EdiValidationError.with_message(
                    f"Invalid processing_mode '{cmd.processing_mode}'.",
                    details={"processing_mode": cmd.processing_mode},
                )
                logger.error(
                    "inbound_route_invalid_processing_mode",
                    processing_mode=cmd.processing_mode,
                    tenant_id=tenant_id,
                    error_code=bad_mode.code,
                )
                return Result.fail(bad_mode)

        create_res = InboundRoute.create(
            tenant_id=tenant_id,
            name=cmd.name,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            trading_partner_id=cmd.trading_partner_id,
            gs_sender_id=cmd.gs_sender_id,
            gs_receiver_id=cmd.gs_receiver_id,
            transaction_type=cmd.transaction_type,
            webhook_id=str(cmd.webhook_id) if cmd.webhook_id else None,
            as2_partner_id=str(cmd.as2_partner_id) if cmd.as2_partner_id else None,
            sftp_partner_id=str(cmd.sftp_partner_id) if cmd.sftp_partner_id else None,
            connection_type=cmd.connection_type,
            processing_mode=mode,
            idempotency_key=idempotency_key,
        )
        if create_res.is_err:
            domain_err = create_res.unwrap_err()
            logger.error(
                "inbound_route_create_validation_failed",
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        aggregate = create_res.unwrap()
        await self.uow.inbound_routes.save(aggregate)

        logger.info(
            "inbound_route_created",
            route_id=aggregate.id,
            tenant_id=tenant_id,
        )
        return Result.ok(aggregate)
