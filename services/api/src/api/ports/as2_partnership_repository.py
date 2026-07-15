from typing import Protocol
from uuid import UUID

from api.domain.models import (
    CreateAS2PartnershipCmd,
    UpdateAS2PartnershipCmd,
)
from domain.models import AS2PartnerDomainModel, AS2PartnershipDomainModel


class AS2PartnershipRepositoryPort(Protocol):
    async def create_as2_partnership(
        self, tenant_id: int, cmd: CreateAS2PartnershipCmd
    ) -> UUID: ...
    async def update_as2_partnership(
        self, tenant_id: int, partnership_id: UUID, cmd: UpdateAS2PartnershipCmd
    ) -> None: ...
    async def get_as2_partnership(
        self, tenant_id: int, partnership_id: UUID
    ) -> AS2PartnershipDomainModel | None: ...
    async def delete_as2_partnership(self, tenant_id: int, partnership_id: UUID) -> None: ...
    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2PartnershipDomainModel, AS2PartnerDomainModel, AS2PartnerDomainModel] | None: ...
