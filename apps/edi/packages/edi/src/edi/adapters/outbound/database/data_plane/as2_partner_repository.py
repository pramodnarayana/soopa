from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.data_plane.exceptions import ReadOnlyDataPlaneRepositoryError
from edi.adapters.outbound.database.data_plane.mappers import as2_partner_to_domain
from edi.adapters.outbound.database.models.data_plane import AS2Partner as OrmAS2Partner
from edi.domain.partner.as2.partner import AS2Partner
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort


class SqlAlchemyDataPlaneAS2PartnerRepository(AS2TradingPartnerRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: AS2Partner) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: AS2Partner) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_as2_partner(self, tenant_id: str, partner_id: str) -> AS2Partner | None:
        stmt = select(OrmAS2Partner).where(
            OrmAS2Partner.tenant_id.in_((PLATFORM_TENANT_ID, tenant_id)),
            OrmAS2Partner.id == partner_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_as2_partner_by_as2_id(self, tenant_id: str, as2_id: str) -> AS2Partner | None:
        stmt = select(OrmAS2Partner).where(
            OrmAS2Partner.tenant_id.in_((PLATFORM_TENANT_ID, tenant_id)),
            OrmAS2Partner.as2_id == as2_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def list_as2_partners(self, tenant_id: str) -> list[AS2Partner]:
        stmt = select(OrmAS2Partner).where(
            OrmAS2Partner.tenant_id.in_((PLATFORM_TENANT_ID, tenant_id))
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def get_as2_partners_by_ids(
        self, tenant_id: str, partner_ids: list[str]
    ) -> list[AS2Partner]:
        if not partner_ids:
            return []
        stmt = select(OrmAS2Partner).where(
            OrmAS2Partner.tenant_id.in_((PLATFORM_TENANT_ID, tenant_id)),
            OrmAS2Partner.id.in_(partner_ids),
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def is_vault_ref_in_use(self, vault_ref: str) -> bool:
        normalized_ref = vault_ref.removeprefix("vault://").strip("/")
        candidate_refs = (normalized_ref, f"vault://{normalized_ref}")
        stmt = (
            select(OrmAS2Partner.id)
            .where(
                or_(
                    OrmAS2Partner.private_key_vault_ref.in_(candidate_refs),
                    OrmAS2Partner.prev_private_key_vault_ref.in_(candidate_refs),
                )
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    @staticmethod
    def _to_domain_model(record: OrmAS2Partner) -> AS2Partner:
        return as2_partner_to_domain(record)
