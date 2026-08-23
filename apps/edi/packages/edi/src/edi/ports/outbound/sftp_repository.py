from collections.abc import Sequence
from typing import Protocol

from edi.application.dto import (
    CreateSFTPPartnerCmd,
    UpdateSFTPPartnerCmd,
)
from edi.domain.models import (
    SFTPPartnerDomainModel,
)


class SFTPPartnerRepositoryPort(Protocol):
    async def create_sftp_partner(self, tenant_id: str, cmd: CreateSFTPPartnerCmd) -> str: ...
    async def update_sftp_partner(
        self, tenant_id: str, partner_id: str, cmd: UpdateSFTPPartnerCmd
    ) -> None: ...
    async def delete_sftp_partner(self, tenant_id: str, partner_id: str) -> None: ...
    async def get_sftp_partner(
        self, tenant_id: str, partner_id: str
    ) -> SFTPPartnerDomainModel | None: ...
    async def list_sftp_partners(self, tenant_id: str) -> Sequence[SFTPPartnerDomainModel]: ...
    async def get_sftp_partners_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]: ...
