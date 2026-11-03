import structlog
from seedwork.domain.exceptions import Result

from edi.domain.exceptions import EdiError, PartnerInUseEdiError, PartnerInUseError
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteSFTPPartnerUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def delete_sftp_partner(
        self, tenant_id: str, partner_id: str, idempotency_key: str | None = None
    ) -> Result[None, EdiError]:
        logger.info(
            "sftp_partner_deletion_started",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        aggregate = await self.uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
        if not aggregate:
            logger.info(
                "sftp_partner_delete_noop_not_found",
                partner_id=partner_id,
                tenant_id=tenant_id,
            )
            return Result.ok(None)

        del_res = aggregate.mark_deleted(idempotency_key=idempotency_key)
        if del_res.is_err:
            domain_err = del_res.unwrap_err()
            logger.error(
                "sftp_partner_delete_rejected",
                partner_id=partner_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        try:
            await self.uow.sftp_partners.delete(aggregate)
        except PartnerInUseError:
            in_use_err = PartnerInUseEdiError.for_id(partner_id, tenant_id)
            logger.error(
                "sftp_partner_delete_in_use",
                partner_id=partner_id,
                tenant_id=tenant_id,
                error_code=in_use_err.code,
            )
            return Result.fail(in_use_err)
        logger.info(
            "sftp_partner_deleted",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        return Result.ok(None)
