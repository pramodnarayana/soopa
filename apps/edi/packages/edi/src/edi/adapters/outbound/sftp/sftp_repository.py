from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update

from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import (
    SFTPPartner,
)
from edi.domain.models.sftp import SFTPPartnerDomainModel
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort


class SqlAlchemySFTPPartnerRepository(SFTPPartnerRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    def _update_record_from_domain(
        self, record: SFTPPartner, aggregate: SFTPPartnerDomainModel
    ) -> None:
        record.tenant_id = aggregate.tenant_id
        record.name = aggregate.name
        record.host = aggregate.host
        record.port = aggregate.port
        record.username = aggregate.username
        record.active = aggregate.active
        record.host_key = aggregate.host_key
        record.inbound_remote_path = aggregate.inbound_remote_path
        record.outbound_remote_path = aggregate.outbound_remote_path
        record.password_encrypted = aggregate.password_encrypted
        record.credentials_vault_ref = aggregate.credentials_vault_ref

    @staticmethod
    def _to_domain_model(record: SFTPPartner) -> SFTPPartnerDomainModel:
        return SFTPPartnerDomainModel(
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

    # ------------------------------------------------------------------------
    # SFTP Partners (Now in Control Plane)
    # ------------------------------------------------------------------------
    async def save(self, aggregate: SFTPPartnerDomainModel) -> None:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.id == aggregate.id,
                SFTPPartner.tenant_id == aggregate.tenant_id,
                SFTPPartner.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            record = SFTPPartner(id=aggregate.id)
            self.session.add(record)

        self._update_record_from_domain(record, aggregate)

        self._drain_events(aggregate)
        await self.session.flush()

    async def get_sftp_partner(
        self, tenant_id: str, partner_id: str
    ) -> SFTPPartnerDomainModel | None:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.id == partner_id,
                SFTPPartner.tenant_id == tenant_id,
                SFTPPartner.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        return self._to_domain_model(record) if record else None

    async def list_sftp_partners(self, tenant_id: str) -> Sequence[SFTPPartnerDomainModel]:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.tenant_id == tenant_id, SFTPPartner.deleted_at.is_(None)
            )
        )
        return [self._to_domain_model(r) for r in result.scalars().all()]

    async def delete(self, aggregate: SFTPPartnerDomainModel) -> None:
        await self.session.execute(
            update(SFTPPartner)
            .where(
                SFTPPartner.id == aggregate.id,
                SFTPPartner.tenant_id == aggregate.tenant_id,
                SFTPPartner.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
        )

        self._drain_events(aggregate)
        await self.session.flush()

    async def get_sftp_partners_by_ids(
        self, tenant_id: str, ids: list[str]
    ) -> list[SFTPPartnerDomainModel]:
        if not ids:
            return []
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.id.in_(ids),
                SFTPPartner.tenant_id == tenant_id,
                SFTPPartner.deleted_at.is_(None),
            )
        )
        return [self._to_domain_model(r) for r in result.scalars().all()]
