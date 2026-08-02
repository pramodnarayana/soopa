import dataclasses
import hashlib
import json
import logging
import uuid

from domain.events import (
    ProvisioningEvent,
)
from domain.models import ConnectionType, PartnerStatus
from soopa_schemas.edi_events import EdiEventType

from api.core.uow import ControlPlaneUnitOfWork
from api.domain.models import (
    UNSET,
    CreateAS2TradingPartnerCmd,
    PartnerEntity,
    UpdateAS2TradingPartnerCmd,
)

logger = logging.getLogger(__name__)


class AS2PartnerService:
    """
    Domain service responsible for the lifecycle of AS2 Trading Partners.
    Operates exclusively on the Global Control Plane repository.
    """

    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def create_as2_partner(
        self, tenant_id: str, cmd: CreateAS2TradingPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Provisioning AS2 partner {cmd.name} for tenant {tenant_id}")

        partner_id = await self.uow.as2_partners.create_as2_identity(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_created,
                resource_id=str(partner_id),
            ),
            idempotency_key=str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS, f"{partner_id}:{EdiEventType.edi_as2_partner_created.value}"
                )
            ),
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            type=ConnectionType.AS2,
            status=PartnerStatus.PROVISIONING,
        )

    async def update_as2_partner(
        self, tenant_id: str, partner_id: str, cmd: UpdateAS2TradingPartnerCmd
    ) -> PartnerEntity:
        logger.info(f"Updating AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.as2_partners.update_as2_identity(tenant_id, partner_id, cmd)

        updated_partner = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not updated_partner:
            raise ValueError("Partner not found after update")

        cmd_dict = dataclasses.asdict(cmd) if dataclasses.is_dataclass(cmd) else cmd.__dict__
        cmd_dict = {k: v for k, v in cmd_dict.items() if v is not UNSET}
        cmd_hash = hashlib.sha256(json.dumps(cmd_dict, sort_keys=True).encode()).hexdigest()
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=str(partner_id),
            ),
            idempotency_key=str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"{partner_id}:{EdiEventType.edi_as2_partner_updated.value}:{cmd_hash}",
                )
            ),
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name or updated_partner.name,
            type=ConnectionType.AS2,
            status=PartnerStatus.ACTIVE if updated_partner.active else PartnerStatus.INACTIVE,
        )

    async def delete_as2_partner(self, tenant_id: str, partner_id: str) -> None:
        logger.info(f"Deleting AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.as2_partners.delete_as2_identity(tenant_id, partner_id)
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_deleted,
                resource_id=str(partner_id),
            ),
            idempotency_key=str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS, f"{partner_id}:{EdiEventType.edi_as2_partner_deleted.value}"
                )
            ),
        )

    async def rotate_certificates(
        self,
        tenant_id: str,
        partner_id: str,
        new_public_cert: str,
        new_private_key_vault_ref: str | None,
    ) -> PartnerEntity:
        logger.info(f"Rotating certificates for AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.as2_partners.rotate_as2_certificates(
            tenant_id, partner_id, new_public_cert, new_private_key_vault_ref
        )

        updated_partner = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not updated_partner:
            raise ValueError("Partner not found after certificate rotation")

        cmd_data = {
            "new_public_cert": new_public_cert,
            "new_private_key_vault_ref": new_private_key_vault_ref,
        }
        cmd_hash = hashlib.sha256(json.dumps(cmd_data, sort_keys=True).encode()).hexdigest()
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=str(partner_id),
            ),
            idempotency_key=str(
                uuid.uuid5(
                    uuid.NAMESPACE_DNS,
                    f"{partner_id}:{EdiEventType.edi_as2_partner_updated.value}:{cmd_hash}",
                )
            ),
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=updated_partner.name,
            type=ConnectionType.AS2,
            status=PartnerStatus.ACTIVE if updated_partner.active else PartnerStatus.INACTIVE,
        )
