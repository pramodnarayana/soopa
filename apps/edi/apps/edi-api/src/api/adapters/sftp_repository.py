from collections.abc import Sequence

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.encryption import db_encryption
from database.models.control_plane import (
    SFTPPartner,
)
from domain.models import SFTPPartnerDomainModel
from sqlalchemy import delete, select

from api.domain.models import (
    CreateSFTPPartnerCmd,
    UpdateSFTPPartnerCmd,
)
from api.ports.sftp_repository import SFTPPartnerRepositoryPort


class SqlAlchemySFTPPartnerRepository(SFTPPartnerRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    # ------------------------------------------------------------------------
    # SFTP Partners (Now in Control Plane)
    # ------------------------------------------------------------------------
    async def create_sftp_partner(self, tenant_id: str, cmd: CreateSFTPPartnerCmd) -> str:
        record = SFTPPartner(
            tenant_id=tenant_id,
            name=cmd.name,
            host=cmd.host,
            port=cmd.port,
            username=cmd.username,
            inbound_remote_path=cmd.inbound_remote_path
            if hasattr(cmd, "inbound_remote_path")
            else None,
            outbound_remote_path=cmd.outbound_remote_path
            if hasattr(cmd, "outbound_remote_path")
            else None,
            password_encrypted=db_encryption.encrypt(cmd.password) if cmd.password else None,
            credentials_vault_ref=cmd.credentials_vault_ref,
            host_key=cmd.host_key,
            active=False,
        )
        self.session.add(record)
        await self.session.flush()
        return record.id

    async def get_sftp_partner(
        self, tenant_id: str, partner_id: str
    ) -> SFTPPartnerDomainModel | None:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.id == partner_id, SFTPPartner.tenant_id == tenant_id
            )
        )
        record = result.scalar_one_or_none()
        return SFTPPartnerDomainModel.model_validate(record) if record else None

    async def list_sftp_partners(self, tenant_id: str) -> Sequence[SFTPPartnerDomainModel]:
        result = await self.session.execute(
            select(SFTPPartner).where(SFTPPartner.tenant_id == tenant_id)
        )
        return [SFTPPartnerDomainModel.model_validate(r) for r in result.scalars().all()]

    async def update_sftp_partner(
        self, tenant_id: str, partner_id: str, cmd: UpdateSFTPPartnerCmd
    ) -> None:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.id == partner_id, SFTPPartner.tenant_id == tenant_id
            )
        )
        partner = result.scalar_one_or_none()
        if partner:
            import dataclasses

            from api.domain.models import UNSET

            update_data = {
                f.name: getattr(cmd, f.name)
                for f in dataclasses.fields(cmd)
                if getattr(cmd, f.name) is not UNSET
            }
            for key, value in update_data.items():
                if key == "password":
                    partner.password_encrypted = db_encryption.encrypt(value) if value else None
                else:
                    setattr(partner, key, value)
        await self.session.flush()

    async def delete_sftp_partner(self, tenant_id: str, partner_id: str) -> None:
        await self.session.execute(
            delete(SFTPPartner).where(
                SFTPPartner.id == partner_id, SFTPPartner.tenant_id == tenant_id
            )
        )
        await self.session.flush()

    async def get_sftp_partners_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(SFTPPartner.id, SFTPPartner.name).where(
                SFTPPartner.id.in_(ids), SFTPPartner.tenant_id == tenant_id
            )
        )
        return {row.id: row.name for row in result.all()}
