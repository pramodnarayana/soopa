import dataclasses
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

        for field in dataclasses.fields(aggregate):
            if field.name not in ("created_at", "updated_at", "_domain_events"):
                setattr(record, field.name, getattr(aggregate, field.name))

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
        return (
            SFTPPartnerDomainModel(
                **{
                    k: v
                    for k, v in record.__dict__.items()
                    if not k.startswith("_") and k not in ("deleted_at", "deleted_by")
                }
            )
            if record
            else None
        )

    async def list_sftp_partners(self, tenant_id: str) -> Sequence[SFTPPartnerDomainModel]:
        result = await self.session.execute(
            select(SFTPPartner).where(
                SFTPPartner.tenant_id == tenant_id, SFTPPartner.deleted_at.is_(None)
            )
        )
        return [
            SFTPPartnerDomainModel(
                **{
                    k: v
                    for k, v in r.__dict__.items()
                    if not k.startswith("_") and k not in ("deleted_at", "deleted_by")
                }
            )
            for r in result.scalars().all()
        ]

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

    async def get_sftp_partners_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(SFTPPartner.id, SFTPPartner.name).where(
                SFTPPartner.id.in_(ids),
                SFTPPartner.tenant_id == tenant_id,
                SFTPPartner.deleted_at.is_(None),
            )
        )
        return {row.id: row.name for row in result.all()}
