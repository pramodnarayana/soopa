import logging
from uuid import UUID

from api.core.uow import UnitOfWork
from api.domain.models import (
    CreateAS2PartnershipCmd,
    PartnerEntity,
    UpdateAS2PartnershipCmd,
)
from domain.events import ProvisioningEventType

logger = logging.getLogger(__name__)


class AS2PartnershipService:
    """
    Domain service responsible for the lifecycle of AS2 Partnerships.
    Validates that referenced local/remote partners exist before mutating state.
    """

    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def create_as2_partnership(
        self, tenant_id: int, cmd: CreateAS2PartnershipCmd
    ) -> PartnerEntity:
        local_partner = await self.uow.control_plane.get_as2_partner(
            tenant_id, cmd.local_partner_id
        )
        if not local_partner:
            raise ValueError(f"Local AS2 partner {cmd.local_partner_id} not found")

        remote_partner = await self.uow.control_plane.get_as2_partner(
            tenant_id, cmd.remote_partner_id
        )
        if not remote_partner:
            raise ValueError(f"Remote AS2 partner {cmd.remote_partner_id} not found")

        logger.info(
            f"Provisioning AS2 partnership {cmd.local_partner_id} -> {cmd.remote_partner_id}"
        )
        partner_id = await self.uow.control_plane.create_as2_partnership(
            tenant_id=tenant_id, cmd=cmd
        )
        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNERSHIP_CREATED,
            payload={"partner_id": str(partner_id), "tenant_id": tenant_id},
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            type="AS2_PARTNERSHIP",
            status="INACTIVE",
        )

    async def update_as2_partnership(
        self, tenant_id: int, partnership_id: UUID, cmd: UpdateAS2PartnershipCmd
    ) -> PartnerEntity:
        check_ids: list[UUID] = []
        if isinstance(cmd.local_partner_id, UUID):
            check_ids.append(cmd.local_partner_id)
        if isinstance(cmd.remote_partner_id, UUID):
            check_ids.append(cmd.remote_partner_id)

        if check_ids:
            valid_partners = await self.uow.control_plane.get_as2_partners_by_ids(
                tenant_id, check_ids
            )
            if len(valid_partners) != len(check_ids):
                raise ValueError(
                    "Invalid local_partner_id or remote_partner_id referenced in update"
                )

        logger.info(f"Updating AS2 partnership {partnership_id}")
        await self.uow.control_plane.update_as2_partnership(
            tenant_id=tenant_id, partnership_id=partnership_id, cmd=cmd
        )
        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNERSHIP_UPDATED,
            payload={"partner_id": str(partnership_id), "tenant_id": tenant_id},
        )
        updated = await self.uow.control_plane.get_as2_partnership(tenant_id, partnership_id)
        if not updated:
            raise ValueError(f"AS2 partnership {partnership_id} not found")

        return PartnerEntity(
            partner_id=partnership_id,
            tenant_id=tenant_id,
            name=updated.name,
            type="AS2_PARTNERSHIP",
            status="ACTIVE" if updated.active else "INACTIVE",
        )

    async def delete_as2_partnership(self, tenant_id: int, partnership_id: UUID) -> None:
        logger.info(f"Deleting AS2 partnership {partnership_id} for tenant {tenant_id}")
        await self.uow.control_plane.delete_as2_partnership(tenant_id, partnership_id)
        await self.uow.control_plane.publish_outbox_event(
            tenant_id=tenant_id,
            event_type=ProvisioningEventType.AS2_PARTNERSHIP_DELETED,
            payload={"partner_id": str(partnership_id), "tenant_id": tenant_id},
        )
