import structlog

from edi.application.dto import (
    CreateAS2PartnershipCmd,
    UpdateAS2PartnershipCmd,
)
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models import (
    AS2PartnershipDomainModel,
)
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork

logger = structlog.get_logger(__name__)


class AS2PartnershipService:
    """
    Domain service responsible for the lifecycle of AS2 Partnerships.
    Validates that referenced local/remote partners exist before mutating state.
    """

    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_as2_partnership(
        self, tenant_id: str, cmd: CreateAS2PartnershipCmd
    ) -> AS2PartnershipDomainModel:
        local_partner = await self.uow.as2_partners.get_as2_partner(
            tenant_id, str(cmd.local_partner_id)
        )
        if not local_partner:
            raise ValueError(f"Local AS2 partner {cmd.local_partner_id} not found")

        remote_partner = await self.uow.as2_partners.get_as2_partner(
            tenant_id, str(cmd.remote_partner_id)
        )
        if not remote_partner:
            raise ValueError(f"Remote AS2 partner {cmd.remote_partner_id} not found")

        logger.info(
            "Provisioning AS2 partnership {cmd.local_partner_id} -> {cmd.remote_partner_id}",
            cmd_local_id=cmd.local_partner_id,
            cmd_remote_id=cmd.remote_partner_id,
        )
        partner_id = await self.uow.as2_partnerships.create_as2_partnership(
            tenant_id=tenant_id, cmd=cmd
        )
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partnership_created,
                resource_id=str(partner_id),
            )
        )

        from datetime import datetime

        return AS2PartnershipDomainModel(
            id=partner_id,
            name="New Partnership",
            local_partner_id=str(cmd.local_partner_id),
            remote_partner_id=str(cmd.remote_partner_id),
            mdn_type=cmd.mdn_type,
            encryption_algorithm=cmd.encryption_algorithm,
            signature_algorithm=cmd.signature_algorithm,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
            tenant_id=tenant_id,
            active=True,
        )

    async def update_as2_partnership(
        self, tenant_id: str, partnership_id: str, cmd: UpdateAS2PartnershipCmd
    ) -> AS2PartnershipDomainModel:
        # Local and remote partner IDs cannot be updated via UpdateAS2PartnershipCmd

        logger.info("Updating AS2 partnership {partnership_id}", partnership_id=partnership_id)
        await self.uow.as2_partnerships.update_as2_partnership(
            tenant_id=tenant_id, partnership_id=partnership_id, cmd=cmd
        )
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partnership_updated,
                resource_id=str(partnership_id),
            )
        )
        updated = await self.uow.as2_partnerships.get_as2_partnership(tenant_id, partnership_id)
        if not updated:
            raise ValueError(f"AS2 partnership {partnership_id} not found")

        return updated

    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None:
        logger.info(
            "Deleting AS2 partnership {partnership_id} for tenant {tenant_id}",
            partnership_id=partnership_id,
            tenant_id=tenant_id,
        )
        await self.uow.as2_partnerships.delete_as2_partnership(tenant_id, partnership_id)
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partnership_deleted,
                resource_id=str(partnership_id),
            )
        )
