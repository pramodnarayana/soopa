import structlog
from seedwork.domain.exceptions import Result

from edi.domain.exceptions import (
    EdiError,
    PartnerInUseEdiError,
    PartnerInUseError,
)
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeleteAS2PartnerUseCase:
    """Use Case for deleting an AS2 Trading Partner."""

    def __init__(self, uow: ControlPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, partner_id: str, idempotency_key: str | None = None
    ) -> Result[None, EdiError]:
        logger.info(
            "delete_as2_partner_started",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        aggregate = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not aggregate:
            logger.info(
                "delete_as2_partner_noop_not_found",
                partner_id=partner_id,
                tenant_id=tenant_id,
            )
            return Result.ok(None)

        del_res = aggregate.mark_deleted(idempotency_key=idempotency_key)
        if del_res.is_err:
            domain_err = del_res.unwrap_err()
            logger.error(
                "delete_as2_partner_domain_rejected",
                partner_id=partner_id,
                tenant_id=tenant_id,
                error_code=domain_err.code,
                reason=domain_err.message,
            )
            return Result.fail(domain_err)

        try:
            await self.uow.as2_partners.delete(aggregate)
        except PartnerInUseError:
            in_use = PartnerInUseEdiError.for_id(partner_id, tenant_id)
            logger.error(
                "delete_as2_partner_in_use",
                partner_id=partner_id,
                tenant_id=tenant_id,
                error_code=in_use.code,
            )
            return Result.fail(in_use)

        logger.info(
            "delete_as2_partner_completed",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        return Result.ok(None)
