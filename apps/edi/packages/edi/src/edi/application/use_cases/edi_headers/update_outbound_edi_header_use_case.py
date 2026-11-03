import dataclasses

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET, UnsetType

from edi.domain.exceptions import EdiError, HeaderNotFoundEdiError
from edi.domain.routing.outbound_header import OutboundEdiHeader
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class UpdateOutboundEdiHeaderCmd:
    trading_partner_id: str | UnsetType = UNSET
    isa_sender_id: str | UnsetType = UNSET
    isa_receiver_id: str | UnsetType = UNSET
    name: str | UnsetType | None = UNSET
    isa_sender_qualifier: str | UnsetType | None = UNSET
    isa_receiver_qualifier: str | UnsetType | None = UNSET
    gs_sender_id: str | UnsetType | None = UNSET
    gs_receiver_id: str | UnsetType | None = UNSET
    transaction_type: str | UnsetType | None = UNSET
    default_standard: str | UnsetType | None = UNSET
    default_version: str | UnsetType | None = UNSET


class UpdateOutboundEdiHeaderUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def update_outbound_edi_header(
        self, tenant_id: str, header_id: str, cmd: UpdateOutboundEdiHeaderCmd
    ) -> Result[OutboundEdiHeader, EdiError]:
        logger.info(
            "outbound_edi_header_update_started",
            header_id=header_id,
            tenant_id=tenant_id,
        )
        aggregate = await self.uow.edi_headers.get_outbound_edi_header(tenant_id, header_id)
        if not aggregate:
            not_found = HeaderNotFoundEdiError.for_id(header_id, tenant_id)
            logger.error(
                "outbound_edi_header_not_found",
                header_id=header_id,
                tenant_id=tenant_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

        upd_res = aggregate.update(
            trading_partner_id=cmd.trading_partner_id,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            name=cmd.name,
            isa_sender_qualifier=cmd.isa_sender_qualifier,
            isa_receiver_qualifier=cmd.isa_receiver_qualifier,
            gs_sender_id=cmd.gs_sender_id,
            gs_receiver_id=cmd.gs_receiver_id,
            transaction_type=cmd.transaction_type,
            default_standard=cmd.default_standard,
            default_version=cmd.default_version,
        )
        if upd_res.is_err:
            domain_err = upd_res.unwrap_err()
            logger.error(
                "outbound_edi_header_update_validation_failed",
                header_id=header_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        await self.uow.edi_headers.save(aggregate)
        logger.info(
            "outbound_edi_header_updated",
            header_id=header_id,
            tenant_id=tenant_id,
        )
        return Result.ok(aggregate)
