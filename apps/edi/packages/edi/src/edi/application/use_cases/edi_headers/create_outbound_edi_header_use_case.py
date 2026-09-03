from datetime import UTC, datetime

import structlog

from edi.application.dtos.commands import CreateOutboundEdiHeaderCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models.headers import OutboundEdiHeaderDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class CreateOutboundEdiHeaderUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_outbound_edi_header(
        self, tenant_id: str, cmd: CreateOutboundEdiHeaderCmd
    ) -> str:
        logger.info(
            "Creating Outbound EDI Header for trading partner {cmd_trading_partner_id} in tenant {tenant_id}",
            cmd_trading_partner_id=cmd.trading_partner_id,
            tenant_id=tenant_id,
        )

        header_id = OutboundEdiHeaderDomainModel.new_id()

        aggregate = OutboundEdiHeaderDomainModel(
            id=header_id,
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
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_header_created,
                resource_id=header_id,
            )
        )

        await self.uow.edi_headers.save(aggregate)

        logger.info(
            "outbound_edi_header_created",
            header_id=header_id,
            tenant_id=tenant_id,
        )
        return header_id
