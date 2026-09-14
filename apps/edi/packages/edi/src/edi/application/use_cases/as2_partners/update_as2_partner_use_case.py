import dataclasses
from typing import Any

import structlog
from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import UNSET, UnsetType
from seedwork.utils import generate_id

from edi.domain.enums import EdiEventType
from edi.domain.events import ProvisioningEvent
from edi.domain.exceptions import PartnerNotFoundError
from edi.domain.models.as2 import AS2PartnerDomainModel
from edi.ports.outbound.uow import ControlPlaneUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclasses.dataclass(frozen=True)
class UpdateAS2TradingPartnerCmd:
    name: str | UnsetType = UNSET
    as2_id: str | UnsetType = UNSET
    is_local: bool | UnsetType = UNSET
    url: str | UnsetType | None = UNSET
    public_cert_pem: str | UnsetType | None = UNSET
    public_cert_vault_ref: str | UnsetType | None = UNSET
    private_key_vault_ref: str | UnsetType | None = UNSET
    active: bool | UnsetType = UNSET


class UpdateAS2PartnerUseCase:
    """
    Use Case for updating an existing AS2 Trading Partner.
    """

    def __init__(self, uow: ControlPlaneUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        partner_id: str,
        cmd: UpdateAS2TradingPartnerCmd,
        idempotency_key: str | None = None,
    ) -> AS2PartnerDomainModel:
        logger.info(
            "update_as2_partner_started",
            id=partner_id,
            tenant_id=tenant_id,
            cmd_fields=dataclasses.asdict(cmd),
        )
        aggregate = await self.uow.as2_partners.get_as2_partner(tenant_id, partner_id)
        if not aggregate:
            raise PartnerNotFoundError(partner_id, tenant_id)

        updated_fields: dict[str, Any] = {}

        if not isinstance(cmd.name, UnsetType):
            aggregate.name = cmd.name
            updated_fields["name"] = cmd.name
        if not isinstance(cmd.as2_id, UnsetType):
            aggregate.as2_id = cmd.as2_id
            updated_fields["as2_id"] = cmd.as2_id
        if not isinstance(cmd.is_local, UnsetType):
            aggregate.is_local = cmd.is_local
            updated_fields["is_local"] = cmd.is_local
        if not isinstance(cmd.url, UnsetType):
            aggregate.url = cmd.url
            updated_fields["url"] = cmd.url
        if not isinstance(cmd.public_cert_pem, UnsetType):
            aggregate.public_cert_pem = cmd.public_cert_pem
            updated_fields["public_cert_pem"] = cmd.public_cert_pem
        if not isinstance(cmd.public_cert_vault_ref, UnsetType):
            aggregate.public_cert_vault_ref = cmd.public_cert_vault_ref
            updated_fields["public_cert_vault_ref"] = cmd.public_cert_vault_ref
        if not isinstance(cmd.private_key_vault_ref, UnsetType):
            aggregate.private_key_vault_ref = cmd.private_key_vault_ref
            updated_fields["private_key_vault_ref"] = cmd.private_key_vault_ref
        if not isinstance(cmd.active, UnsetType):
            aggregate.active = cmd.active
            updated_fields["active"] = cmd.active

        logger.info(
            "update_as2_partner_fields_resolved",
            id=partner_id,
            tenant_id=tenant_id,
            updated_fields=updated_fields,
            final_active_status=aggregate.active,
        )

        aggregate.add_domain_event(
            ProvisioningEvent(
                tenant_id=tenant_id,
                event_type=EdiEventType.edi_as2_partner_updated,
                resource_id=partner_id,
                idempotency_key=idempotency_key or generate_id(SystemIdPrefix.GENERIC),
            )
        )

        await self.uow.as2_partners.save(aggregate)

        logger.info(
            "update_as2_partner_completed",
            id=partner_id,
            tenant_id=tenant_id,
        )

        return aggregate
