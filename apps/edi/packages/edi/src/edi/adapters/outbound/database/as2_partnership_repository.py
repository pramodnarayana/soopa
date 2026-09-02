import dataclasses

from sqlalchemy import delete, select

from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import AS2Partnership
from edi.adapters.outbound.database.repository import PartnershipRepository
from edi.domain.models.as2 import AS2PartnerDomainModel, AS2PartnershipDomainModel
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort


class SqlAlchemyAS2PartnershipRepository(AS2PartnershipRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def list_as2_partnerships(self, tenant_id: str) -> list[AS2PartnershipDomainModel]:
        result = await self.session.execute(
            select(AS2Partnership).where(AS2Partnership.tenant_id == tenant_id)
        )
        return [
            AS2PartnershipDomainModel(
                **{
                    f.name: getattr(r, f.name)
                    for f in dataclasses.fields(AS2PartnershipDomainModel)
                }
            )
            for r in result.scalars().all()
        ]

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2PartnershipDomainModel, AS2PartnerDomainModel, AS2PartnerDomainModel] | None:

        repo = PartnershipRepository(self.session)
        result = await repo.get_partnership_by_as2_ids(as2_from, as2_to)
        if not result:
            return None

        partnership_orm, local_partner_orm, remote_partner_orm = result

        return (
            AS2PartnershipDomainModel(
                **{
                    f.name: getattr(partnership_orm, f.name)
                    for f in dataclasses.fields(AS2PartnershipDomainModel)
                }
            ),
            AS2PartnerDomainModel(
                **{
                    f.name: getattr(local_partner_orm, f.name)
                    for f in dataclasses.fields(AS2PartnerDomainModel)
                }
            ),
            AS2PartnerDomainModel(
                **{
                    f.name: getattr(remote_partner_orm, f.name)
                    for f in dataclasses.fields(AS2PartnerDomainModel)
                }
            ),
        )

    async def save(self, aggregate: AS2PartnershipDomainModel) -> None:
        tid_str = aggregate.tenant_id
        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == aggregate.id,
                AS2Partnership.tenant_id == tid_str,
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            record = AS2Partnership(id=aggregate.id)
            self.session.add(record)

        for field in dataclasses.fields(aggregate):
            if field.name not in ("created_at", "updated_at", "_domain_events"):
                setattr(record, field.name, getattr(aggregate, field.name))

        self._drain_events(aggregate)
        await self.session.flush()

    async def delete(self, aggregate: AS2PartnershipDomainModel) -> None:
        tid_str = aggregate.tenant_id
        await self.session.execute(
            delete(AS2Partnership).where(
                AS2Partnership.id == aggregate.id, AS2Partnership.tenant_id == tid_str
            )
        )
        self._drain_events(aggregate)
        await self.session.flush()

    async def get_as2_partnership(
        self, tenant_id: str, partnership_id: str
    ) -> AS2PartnershipDomainModel | None:
        tid_str = tenant_id
        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tid_str
            )
        )
        record = result.scalar_one_or_none()
        return (
            AS2PartnershipDomainModel(
                **{
                    f.name: getattr(record, f.name)
                    for f in dataclasses.fields(AS2PartnershipDomainModel)
                }
            )
            if record
            else None
        )
