import structlog

from edi.domain.events import EdiEventType, ProvisioningEvent
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
        await self.uow.sftp_partners.delete_sftp_partner(tenant_id, partner_id)

        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_deleted,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )
