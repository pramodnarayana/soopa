import dataclasses

from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import delete, or_, select

from database.exceptions import DuplicateEntityError, ForeignKeyViolationError
from database.interceptors import intercept_db_errors
from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import AS2Partner
from edi.domain.exceptions import PartnerAlreadyExistsError, PartnerInUseError
from edi.domain.models.as2 import AS2PartnerDomainModel
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort


class SqlAlchemyAS2TradingPartnerRepository(
    AS2TradingPartnerRepositoryPort, GlobalSqlAlchemyRepository
):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def save(self, aggregate: AS2PartnerDomainModel) -> None:
        if aggregate.tenant_id and aggregate.tenant_id != PLATFORM_TENANT_ID:
            raise ValueError(
                f"AS2Partner must be a global configuration. Expected tenant_id={PLATFORM_TENANT_ID}"
            )
        conds = [AS2Partner.id == aggregate.id, AS2Partner.tenant_id == PLATFORM_TENANT_ID]

        result = await self.session.execute(select(AS2Partner).where(*conds))
        record = result.scalar_one_or_none()

        if record is None:
            record = AS2Partner(id=aggregate.id)
            self.session.add(record)

        for field in dataclasses.fields(aggregate):
            if field.name not in ("created_at", "updated_at", "_domain_events"):
                setattr(record, field.name, getattr(aggregate, field.name))

        self._drain_events(aggregate)

        try:
            await self.flush()
        except DuplicateEntityError as e:
            if e.constraint_name and "uq_tenant_as2_id" in e.constraint_name:
                raise PartnerAlreadyExistsError(
                    as2_id=str(aggregate.as2_id),
                    tenant_id=aggregate.tenant_id or PLATFORM_TENANT_ID,
                ) from e
            raise

    async def get_as2_partner(
        self, tenant_id: str, partner_id: str
    ) -> AS2PartnerDomainModel | None:
        stmt = select(AS2Partner).where(
            AS2Partner.tenant_id == PLATFORM_TENANT_ID, AS2Partner.id == partner_id
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        return (
            AS2PartnerDomainModel(
                **{
                    f.name: getattr(record, f.name)
                    for f in dataclasses.fields(AS2PartnerDomainModel)
                }
            )
            if record
            else None
        )

    async def is_vault_ref_in_use(self, tenant_id: str, vault_ref: str) -> bool:
        stmt = select(AS2Partner).where(
            AS2Partner.tenant_id == PLATFORM_TENANT_ID,
            or_(
                AS2Partner.private_key_vault_ref == vault_ref,
                AS2Partner.prev_private_key_vault_ref == vault_ref,
            ),
        )
        res = await self.session.execute(stmt)
        return res.scalars().first() is not None

    async def list_as2_partners(self, tenant_id: str) -> list[AS2PartnerDomainModel]:
        result = await self.session.execute(
            select(AS2Partner).where(AS2Partner.tenant_id == PLATFORM_TENANT_ID)
        )
        return [
            AS2PartnerDomainModel(
                **{f.name: getattr(r, f.name) for f in dataclasses.fields(AS2PartnerDomainModel)}
            )
            for r in result.scalars().all()
        ]

    async def delete(self, aggregate: AS2PartnerDomainModel) -> None:
        conds = [AS2Partner.id == aggregate.id, AS2Partner.tenant_id == PLATFORM_TENANT_ID]

        try:
            async with intercept_db_errors():
                await self.session.execute(delete(AS2Partner).where(*conds))
                self._drain_events(aggregate)
                await self.flush()
        except ForeignKeyViolationError as e:
            raise PartnerInUseError(
                partner_id=str(aggregate.id), tenant_id=aggregate.tenant_id or PLATFORM_TENANT_ID
            ) from e

    async def get_as2_partners_by_ids(
        self, tenant_id: str, partner_ids: list[str]
    ) -> list[AS2PartnerDomainModel]:
        if not partner_ids:
            return []

        stmt = select(AS2Partner).where(
            AS2Partner.tenant_id == PLATFORM_TENANT_ID, AS2Partner.id.in_(partner_ids)
        )
        result = await self.session.execute(stmt)
        return [
            AS2PartnerDomainModel(
                **{f.name: getattr(r, f.name) for f in dataclasses.fields(AS2PartnerDomainModel)}
            )
            for r in result.scalars().all()
        ]
