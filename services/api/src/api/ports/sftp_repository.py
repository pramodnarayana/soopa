from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from api.domain.models import (
    CreateSFTPPartnerCmd,
    UpdateSFTPPartnerCmd,
)
from domain.models import SFTPPartnerDomainModel


class SFTPPartnerRepositoryPort(Protocol):
    async def create_sftp_partner(self, tenant_id: int, cmd: CreateSFTPPartnerCmd) -> UUID: ...
    async def update_sftp_partner(
        self, tenant_id: int, partner_id: UUID, cmd: UpdateSFTPPartnerCmd
    ) -> None: ...
    async def delete_sftp_partner(self, tenant_id: int, partner_id: UUID) -> None: ...
    async def get_sftp_partner(
        self, tenant_id: int, partner_id: UUID
    ) -> SFTPPartnerDomainModel | None: ...
    async def list_sftp_partners(self, tenant_id: int) -> Sequence[SFTPPartnerDomainModel]: ...
    async def get_sftp_partners_by_ids(
        self, tenant_id: int, ids: list[UUID]
    ) -> dict[UUID, str]: ...
