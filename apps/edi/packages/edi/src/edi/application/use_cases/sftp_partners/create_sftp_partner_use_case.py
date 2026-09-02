import os
from datetime import UTC, datetime

import structlog

from edi.application.dto import CreateSFTPPartnerCmd
from edi.domain.events import EdiEventType, ProvisioningEvent
from edi.domain.models.sftp import SFTPPartnerDomainModel
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

        partner_id = f"{SFTPPartnerDomainModel.ID_PREFIX}_{os.urandom(12).hex()}"

        aggregate = SFTPPartnerDomainModel(
            id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            host=cmd.host,
            port=cmd.port,
            username=cmd.username,
            inbound_remote_path=cmd.inbound_remote_path,
            outbound_remote_path=cmd.outbound_remote_path,
            credentials_vault_ref=cmd.credentials_vault_ref,
            active=False,
            created_at=datetime.now(UTC).replace(tzinfo=None),
            updated_at=datetime.now(UTC).replace(tzinfo=None),
        )

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_sftp_partner_created,
                resource_id=partner_id,
                explicit_idempotency_key=idempotency_key,
            )
        )

        await self.uow.sftp_partners.save(aggregate)

        logger.info(
            "sftp_partner_created",
            partner_id=partner_id,
            tenant_id=tenant_id,
        )
        return aggregate
