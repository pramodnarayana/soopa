from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select, update

from database.exceptions import (
    DuplicateEntityError,
    ForeignKeyViolationError,
)
from database.interceptors import intercept_db_errors
from edi.adapters.outbound.database.base_repository import (
    GlobalSession,
    GlobalSqlAlchemyRepository,
)
from edi.adapters.outbound.database.models.control_plane import SFTPPartner as OrmSFTPPartner
from edi.domain.exceptions import PartnerInUseError, SftpPartnerAlreadyExistsError
from edi.domain.partner.sftp.partner import SFTPPartner
from edi.ports.outbound.sftp_repository import SFTPPartnerRepositoryPort


class SqlAlchemySFTPPartnerRepository(SFTPPartnerRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    def _update_record_from_domain(self, record: OrmSFTPPartner, aggregate: SFTPPartner) -> None:
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

    async def save(self, aggregate: SFTPPartner) -> None:
        result = await self.session.execute(
            select(OrmSFTPPartner).where(
                OrmSFTPPartner.id == aggregate.id,
                OrmSFTPPartner.tenant_id == aggregate.tenant_id,
                OrmSFTPPartner.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            record = OrmSFTPPartner(id=aggregate.id)
            self.session.add(record)

        self._update_record_from_domain(record, aggregate)

        await self._drain_events(aggregate)
        try:
            await self.flush()
        except DuplicateEntityError as exc:
            raise SftpPartnerAlreadyExistsError(
                name=aggregate.name,
                tenant_id=aggregate.tenant_id,
            ) from exc

    async def get_sftp_partner(self, tenant_id: str, partner_id: str) -> SFTPPartner | None:
        result = await self.session.execute(
            select(OrmSFTPPartner).where(
                OrmSFTPPartner.id == partner_id,
                OrmSFTPPartner.tenant_id == tenant_id,
                OrmSFTPPartner.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        return self._to_domain_model(record) if record else None

    async def list_sftp_partners(self, tenant_id: str) -> Sequence[SFTPPartner]:
        result = await self.session.execute(
            select(OrmSFTPPartner).where(
                OrmSFTPPartner.tenant_id == tenant_id, OrmSFTPPartner.deleted_at.is_(None)
            )
        )
        return [self._to_domain_model(r) for r in result.scalars().all()]

    async def delete(self, aggregate: SFTPPartner) -> None:
        try:
            async with intercept_db_errors():
                await self.session.execute(
                    update(OrmSFTPPartner)
                    .where(
                        OrmSFTPPartner.id == aggregate.id,
                        OrmSFTPPartner.tenant_id == aggregate.tenant_id,
                        OrmSFTPPartner.deleted_at.is_(None),
                    )
                    .values(deleted_at=datetime.now(UTC).replace(tzinfo=None))
                )
                await self._drain_events(aggregate)
                await self.flush()
        except (ForeignKeyViolationError, DuplicateEntityError) as exc:
            raise PartnerInUseError(
                partner_id=str(aggregate.id),
                tenant_id=aggregate.tenant_id,
            ) from exc

    async def get_sftp_partners_by_ids(self, tenant_id: str, ids: list[str]) -> list[SFTPPartner]:
        if not ids:
            return []
        result = await self.session.execute(
            select(OrmSFTPPartner).where(
                OrmSFTPPartner.id.in_(ids),
                OrmSFTPPartner.tenant_id == tenant_id,
                OrmSFTPPartner.deleted_at.is_(None),
            )
        )
        return [self._to_domain_model(r) for r in result.scalars().all()]
