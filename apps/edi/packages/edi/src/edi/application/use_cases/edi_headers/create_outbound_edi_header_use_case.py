from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from edi.domain.exceptions import EdiError
from edi.domain.routing.outbound_header import OutboundEdiHeader
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateOutboundEdiHeaderCmd:
    trading_partner_id: str
    isa_sender_id: str
    isa_receiver_id: str
    name: str | None = None
    isa_sender_qualifier: str | None = None
    isa_receiver_qualifier: str | None = None
    gs_sender_id: str | None = None
    gs_receiver_id: str | None = None
    transaction_type: str | None = None
    default_standard: str | None = None
    default_version: str | None = None
    isa_control_version: str | None = None
    isa_usage_indicator: str | None = None
    gs_version: str | None = None
    segment_terminator: str | None = None
    element_separator: str | None = None
    subelement_separator: str | None = None


class CreateOutboundEdiHeaderUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_outbound_edi_header(
        self, tenant_id: str, cmd: CreateOutboundEdiHeaderCmd
    ) -> Result[str, EdiError]:
        logger.info(
            "outbound_edi_header_create_started",
            trading_partner_id=cmd.trading_partner_id,
            tenant_id=tenant_id,
        )

        create_res = OutboundEdiHeader.create(
            tenant_id=tenant_id,
            name=cmd.name,
            trading_partner_id=cmd.trading_partner_id,
            isa_sender_id=cmd.isa_sender_id,
            isa_sender_qualifier=cmd.isa_sender_qualifier,
            isa_receiver_id=cmd.isa_receiver_id,
            isa_receiver_qualifier=cmd.isa_receiver_qualifier,
            isa_control_version=cmd.isa_control_version,
            isa_usage_indicator=cmd.isa_usage_indicator,
            gs_sender_id=cmd.gs_sender_id,
            gs_receiver_id=cmd.gs_receiver_id,
            gs_version=cmd.gs_version,
            transaction_type=cmd.transaction_type,
            default_standard=cmd.default_standard,
            default_version=cmd.default_version,
            segment_terminator=cmd.segment_terminator,
            element_separator=cmd.element_separator,
            subelement_separator=cmd.subelement_separator,
        )
        if create_res.is_err:
            domain_err = create_res.unwrap_err()
            logger.error(
                "outbound_edi_header_create_validation_failed",
                trading_partner_id=cmd.trading_partner_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        aggregate = create_res.unwrap()
        await self.uow.edi_headers.save(aggregate)

        logger.info(
            "outbound_edi_header_created",
            header_id=aggregate.id,
            tenant_id=tenant_id,
        )
        return Result.ok(aggregate.id)
