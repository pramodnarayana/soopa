import structlog

from edi.application.dto import CreateSFTPPartnerCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models import SFTPPartnerDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class CreateSFTPPartnerUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_sftp_partner(
        self, tenant_id: str, cmd: CreateSFTPPartnerCmd, idempotency_key: str | None = None
    ) -> SFTPPartnerDomainModel:
        logger.info(
            "Creating SFTP partner {cmd_name} for tenant {tenant_id}",
            cmd_name=cmd.name,
            tenant_id=tenant_id,
        )
        partner_id = await self.uow.sftp_partners.create_sftp_partner(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane_outbox.publish_outbox_event(
            event=ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_created,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )

        from datetime import datetime

        return SFTPPartnerDomainModel(
            id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            host=cmd.host,
            port=cmd.port,
            username=cmd.username,
            active=False,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
