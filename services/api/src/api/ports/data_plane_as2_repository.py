from typing import Protocol
from uuid import UUID

from domain.models import AS2PartnerDomainModel, AS2PartnershipDomainModel


class DataPlaneAS2RepositoryPort(Protocol):
    async def get_as2_partnership(
        self, tenant_id: int, partnership_id: UUID
    ) -> AS2PartnershipDomainModel | None: ...
    async def get_as2_partner(
        self, tenant_id: int, partner_id: UUID
    ) -> AS2PartnerDomainModel | None: ...
