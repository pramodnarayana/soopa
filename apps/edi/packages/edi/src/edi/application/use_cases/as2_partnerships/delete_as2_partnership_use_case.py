import structlog
from seedwork.domain.exceptions import Result

from edi.domain.exceptions import EdiError
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteAS2PartnershipUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def delete_as2_partnership(
        self, tenant_id: str, partnership_id: str
    ) -> Result[None, EdiError]:
        logger.info(
            "edi_as2_partnership_deletion_started",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )

        aggregate = await self.uow.as2_partnerships.get_as2_partnership(tenant_id, partnership_id)
        if not aggregate:
            logger.info(
                "edi_as2_partnership_delete_noop_not_found",
                partnership_id=partnership_id,
                tenant_id=tenant_id,
            )
            return Result.ok(None)

        del_res = aggregate.mark_deleted()
        if del_res.is_err:
            domain_err = del_res.unwrap_err()
            logger.error(
                "edi_as2_partnership_delete_rejected",
                partnership_id=partnership_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        await self.uow.as2_partnerships.delete(aggregate)

        logger.info(
            "edi_as2_partnership_deleted",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )
        return Result.ok(None)
