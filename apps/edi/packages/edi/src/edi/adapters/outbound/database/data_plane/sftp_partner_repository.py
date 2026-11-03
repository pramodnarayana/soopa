from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.data_plane.exceptions import ReadOnlyDataPlaneRepositoryError
from edi.adapters.outbound.database.models.data_plane import SFTPPartner as OrmSFTPPartner
from edi.domain.partner.sftp.partner import SFTPPartner
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort


class SqlAlchemyDataPlaneSFTPPartnerRepository(SFTPPartnerRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: SFTPPartner) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: SFTPPartner) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_sftp_partner(self, tenant_id: str, partner_id: str) -> SFTPPartner | None:
        stmt = select(OrmSFTPPartner).where(
            OrmSFTPPartner.tenant_id == tenant_id, OrmSFTPPartner.id == partner_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def list_sftp_partners(self, tenant_id: str) -> list[SFTPPartner]:
        stmt = select(OrmSFTPPartner).where(OrmSFTPPartner.tenant_id == tenant_id)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def get_sftp_partners_by_ids(
        self, tenant_id: str, partner_ids: list[str]
    ) -> list[SFTPPartner]:
        stmt = select(OrmSFTPPartner).where(
            OrmSFTPPartner.tenant_id == tenant_id, OrmSFTPPartner.id.in_(partner_ids)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: OrmSFTPPartner) -> SFTPPartner:
        return SFTPPartner(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            host=record.host,
            port=record.port,
            username=record.username,
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            host_key=record.host_key,
            inbound_remote_path=record.inbound_remote_path,
            outbound_remote_path=record.outbound_remote_path,
            password_encrypted=record.password_encrypted,
            credentials_vault_ref=record.credentials_vault_ref,
        )
