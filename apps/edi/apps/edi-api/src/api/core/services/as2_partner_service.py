import logging
import typing

from domain.events import (
    ProvisioningEvent,
)
from domain.models import ConnectionType, PartnerStatus
from platform_schemas.edi_events import EdiEventType

from api.core.uow import ControlPlaneUnitOfWork
from api.domain.models import (
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

    async def check_and_reserve_idempotency(
        self, tenant_id: str, request_data: dict[str, typing.Any], idempotency_key: str
    ) -> PartnerEntity | None:
        import hashlib
        import json

        from database.models.control_plane import ControlPlaneOutbox
        from fastapi import HTTPException
        from sqlalchemy import insert, select
        from sqlalchemy.exc import IntegrityError

        fingerprint = hashlib.sha256(json.dumps(request_data, sort_keys=True).encode()).hexdigest()

        try:
            insert_stmt = insert(ControlPlaneOutbox).values(
                id=f"reservation_{idempotency_key}",
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                event_type="RESERVATION",
                payload={"fingerprint": fingerprint},
                status="RESERVED",
                attempts=0,
            )
            await self.uow.global_session.execute(insert_stmt)
            await self.uow.global_session.flush()
        except IntegrityError:
            select_stmt = select(ControlPlaneOutbox).where(
                ControlPlaneOutbox.idempotency_key == idempotency_key
            )
            result = await self.uow.global_session.execute(select_stmt)
            existing_event = result.scalar_one_or_none()

            if existing_event and existing_event.payload:
                existing_fingerprint = existing_event.payload.get("fingerprint")
                if existing_fingerprint != fingerprint:
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency conflict: payload does not match existing request.",
                    ) from None

                partner_id = existing_event.payload.get("resource_id")
                if partner_id:
                    existing_partner = await self.uow.as2_partners.get_as2_partner(
                        tenant_id, partner_id
                    )
                    if existing_partner:
                        return PartnerEntity(
                            partner_id=partner_id,
                            tenant_id=tenant_id,
                            name=existing_partner.name,
                            type=ConnectionType.AS2,
                            status=PartnerStatus.PROVISIONING,
                        )
        return None

    async def create_as2_partner(
        self, tenant_id: str, cmd: CreateAS2TradingPartnerCmd, idempotency_key: str | None = None
    ) -> PartnerEntity:
        logger.info(f"Provisioning AS2 partner {cmd.name} for tenant {tenant_id}")

        partner_id = await self.uow.as2_partners.create_as2_identity(tenant_id=tenant_id, cmd=cmd)
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_created,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            type=ConnectionType.AS2,
            status=PartnerStatus.PROVISIONING,
        )

    async def update_as2_partner(
        self,
        tenant_id: str,
        partner_id: str,
        cmd: UpdateAS2TradingPartnerCmd,
        idempotency_key: str | None = None,
    ) -> PartnerEntity:
        logger.info(f"Updating AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.as2_partners.update_as2_identity(tenant_id, partner_id, cmd)

        updated_partner = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not updated_partner:
            raise ValueError("Partner not found after update")

        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name or updated_partner.name,
            type=ConnectionType.AS2,
            status=PartnerStatus.ACTIVE if updated_partner.active else PartnerStatus.INACTIVE,
        )

    async def delete_as2_partner(
        self, tenant_id: str, partner_id: str, idempotency_key: str | None = None
    ) -> None:
        logger.info(f"Deleting AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.as2_partners.delete_as2_identity(tenant_id, partner_id)
        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_deleted,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )

    async def rotate_certificates(
        self,
        tenant_id: str,
        partner_id: str,
        new_public_cert: str,
        new_private_key_vault_ref: str | None,
        idempotency_key: str | None = None,
    ) -> PartnerEntity:
        logger.info(f"Rotating certificates for AS2 partner {partner_id} for tenant {tenant_id}")
        await self.uow.as2_partners.rotate_as2_certificates(
            tenant_id, partner_id, new_public_cert, new_private_key_vault_ref
        )

        updated_partner = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not updated_partner:
            raise ValueError("Partner not found after certificate rotation")

        await self.uow.control_plane_outbox.publish_outbox_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=str(partner_id),
            ),
            idempotency_key=idempotency_key,
        )

        return PartnerEntity(
            partner_id=partner_id,
            tenant_id=tenant_id,
            name=updated_partner.name,
            type=ConnectionType.AS2,
            status=PartnerStatus.ACTIVE if updated_partner.active else PartnerStatus.INACTIVE,
        )
