import dataclasses

from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, func, select
from sqlalchemy.orm import aliased

from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import AS2Partner, AS2Partnership
from edi.domain.exceptions import DomainError
from edi.domain.models.as2 import AS2PartnerDomainModel, AS2PartnershipDomainModel
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort


class PartnershipAlreadyExistsError(DomainError):
    def __init__(self, tenant_id: str, local_partner_id: str, remote_partner_id: str):
        super().__init__(
            f"An active partnership already exists between '{local_partner_id}' and '{remote_partner_id}' for tenant '{tenant_id}'."
        )


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

    async def get_as2_partnerships_by_remote_partner_id(
        self, tenant_id: str, remote_partner_id: str, active: bool | None = None
    ) -> list[AS2PartnershipDomainModel]:
        stmt = select(AS2Partnership).where(
            AS2Partnership.tenant_id == tenant_id,
            AS2Partnership.remote_partner_id == remote_partner_id,
        )
        if active is not None:
            stmt = stmt.where(AS2Partnership.active.is_(active))
        records = (await self.session.execute(stmt)).scalars().all()
        return [
            AS2PartnershipDomainModel(
                **{
                    f.name: getattr(r, f.name)
                    for f in dataclasses.fields(AS2PartnershipDomainModel)
                }
            )
            for r in records
        ]

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2PartnershipDomainModel, AS2PartnerDomainModel, AS2PartnerDomainModel] | None:

        LocalPartner = aliased(AS2Partner)
        RemotePartner = aliased(AS2Partner)

        stmt = (
            select(AS2Partnership, LocalPartner, RemotePartner)
            .join(LocalPartner, AS2Partnership.local_partner_id == LocalPartner.id)
            .join(RemotePartner, AS2Partnership.remote_partner_id == RemotePartner.id)
            .where(
                AS2Partnership.tenant_id == PLATFORM_TENANT_ID,
                func.lower(LocalPartner.as2_id) == as2_to.lower(),
                func.lower(RemotePartner.as2_id) == as2_from.lower(),
                AS2Partnership.active.is_(True),
                LocalPartner.active.is_(True),
                RemotePartner.active.is_(True),
            )
        )

        result = await self.session.execute(stmt)
        row = result.first()
        if not row:
            return None

        partnership_orm, local_partner_orm, remote_partner_orm = row

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
        if aggregate.tenant_id and aggregate.tenant_id != PLATFORM_TENANT_ID:
            raise ValueError(
                f"AS2Partnership must be a global configuration. Expected tenant_id={PLATFORM_TENANT_ID}"
            )

        if aggregate.active:
            existing_active = await self.session.execute(
                select(AS2Partnership).where(
                    AS2Partnership.tenant_id == aggregate.tenant_id,
                    AS2Partnership.local_partner_id == aggregate.local_partner_id,
                    AS2Partnership.remote_partner_id == aggregate.remote_partner_id,
                    AS2Partnership.active.is_(True),
                    AS2Partnership.id != aggregate.id,
                )
            )
            if existing_active.first():
                raise PartnershipAlreadyExistsError(
                    tenant_id=PLATFORM_TENANT_ID,
                    local_partner_id=aggregate.local_partner_id,
                    remote_partner_id=aggregate.remote_partner_id,
                )

        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == aggregate.id,
                AS2Partnership.tenant_id == aggregate.tenant_id,
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
        await self.session.execute(
            delete(AS2Partnership).where(
                AS2Partnership.id == aggregate.id, AS2Partnership.tenant_id == aggregate.tenant_id
            )
        )
        self._drain_events(aggregate)
        await self.session.flush()

    async def get_as2_partnership_by_identifiers(
        self, tenant_id: str, local_partner_id: str, remote_partner_id: str
    ) -> AS2PartnershipDomainModel | None:
        stmt = select(AS2Partnership).where(
            AS2Partnership.tenant_id == tenant_id,
            AS2Partnership.local_partner_id == local_partner_id,
            AS2Partnership.remote_partner_id == remote_partner_id,
        )
        record = (await self.session.execute(stmt)).scalar_one_or_none()
        if not record:
            return None
        return AS2PartnershipDomainModel(
            **{
                f.name: getattr(record, f.name)
                for f in dataclasses.fields(AS2PartnershipDomainModel)
            }
        )

    async def get_as2_partnership(
        self, tenant_id: str, partnership_id: str
    ) -> AS2PartnershipDomainModel | None:
        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == partnership_id, AS2Partnership.tenant_id == tenant_id
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
