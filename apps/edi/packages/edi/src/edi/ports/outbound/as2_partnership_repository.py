from typing import Protocol

from domain.models import AS2PartnerDomainModel, AS2PartnershipDomainModel

from edi.domain.models import (
    CreateAS2PartnershipCmd,
    UpdateAS2PartnershipCmd,
)


class AS2PartnershipRepositoryPort(Protocol):
    async def list_as2_partnerships(self, tenant_id: str) -> list[AS2PartnershipDomainModel]: ...
    async def create_as2_partnership(self, tenant_id: str, cmd: CreateAS2PartnershipCmd) -> str: ...
    async def update_as2_partnership(
        self, tenant_id: str, partnership_id: str, cmd: UpdateAS2PartnershipCmd
    ) -> None: ...
    async def get_as2_partnership(
        self, tenant_id: str, partnership_id: str
    ) -> AS2PartnershipDomainModel | None: ...
    async def delete_as2_partnership(self, tenant_id: str, partnership_id: str) -> None: ...
    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2PartnershipDomainModel, AS2PartnerDomainModel, AS2PartnerDomainModel] | None: ...
