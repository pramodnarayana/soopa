from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from domain.models import AS2PartnerDomainModel

from api.domain.models import (
    CreateAS2TradingPartnerCmd,
    UpdateAS2TradingPartnerCmd,
)


class AS2TradingPartnerRepositoryPort(Protocol):
    async def create_as2_identity(
        self, tenant_id: str, cmd: CreateAS2TradingPartnerCmd
    ) -> UUID: ...
    async def update_as2_identity(
        self, tenant_id: str, partner_id: UUID, cmd: UpdateAS2TradingPartnerCmd
    ) -> None: ...
    async def rotate_as2_certificates(
        self,
        tenant_id: str,
        partner_id: UUID,
        new_public_cert: str,
        new_private_key_vault_ref: str | None,
    ) -> None: ...
    async def get_as2_partner(
        self, tenant_id: str, partner_id: UUID
    ) -> AS2PartnerDomainModel | None: ...
    async def delete_as2_identity(self, tenant_id: str, partner_id: UUID) -> None: ...
    async def get_as2_partners_by_ids(self, tenant_id: str, ids: list[UUID]) -> dict[UUID, str]: ...
    async def list_as2_partners(self, tenant_id: str) -> Sequence[AS2PartnerDomainModel]: ...
