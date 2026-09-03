import structlog

from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class DeleteSFTPPartnerUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def delete_sftp_partner(
        self, tenant_id: str, partner_id: str, idempotency_key: str | None = None
    ) -> None:
        logger.info(
            "Deleting SFTP partner {partner_id} for tenant {tenant_id}",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        aggregate = await self.uow.sftp_partners.get_sftp_partner(tenant_id, partner_id)
        if not aggregate:
            return

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_deleted,
                resource_id=partner_id,
                explicit_idempotency_key=idempotency_key,
            )
        )

        await self.uow.sftp_partners.delete(aggregate)
