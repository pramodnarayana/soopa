import structlog
from seedwork.domain.exceptions import Result

from edi.domain.exceptions import EdiError, HeaderNotFoundEdiError
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteOutboundEdiHeaderUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def delete_outbound_edi_header(
        self, tenant_id: str, header_id: str
    ) -> Result[None, EdiError]:
        logger.info(
            "outbound_edi_header_delete_started",
            header_id=header_id,
            tenant_id=tenant_id,
        )
        aggregate = await self.uow.edi_headers.get_outbound_edi_header(tenant_id, header_id)
        if not aggregate:
            not_found = HeaderNotFoundEdiError.for_id(header_id, tenant_id)
            logger.error(
                "outbound_edi_header_delete_not_found",
                header_id=header_id,
                tenant_id=tenant_id,
                error_code=not_found.code,
            )
            return Result.fail(not_found)

        del_res = aggregate.mark_deleted()
        if del_res.is_err:
            domain_err = del_res.unwrap_err()
            logger.error(
                "outbound_edi_header_delete_rejected",
                header_id=header_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        await self.uow.edi_headers.delete(aggregate)
        logger.info(
            "outbound_edi_header_deleted",
            header_id=header_id,
            tenant_id=tenant_id,
        )

        return Result.ok(None)
