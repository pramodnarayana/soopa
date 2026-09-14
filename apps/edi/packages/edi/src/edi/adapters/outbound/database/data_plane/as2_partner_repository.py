from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.data_plane.exceptions import ReadOnlyDataPlaneRepositoryError
from edi.adapters.outbound.database.models.data_plane import AS2Partner
from edi.domain.models.as2 import AS2PartnerDomainModel
from edi.ports.outbound.as2_partner_repository import AS2TradingPartnerRepositoryPort


class SqlAlchemyDataPlaneAS2PartnerRepository(AS2TradingPartnerRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: AS2PartnerDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: AS2PartnerDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_as2_partner(
        self, tenant_id: str, remote_partner_id: str
    ) -> AS2PartnerDomainModel | None:
        stmt = select(AS2Partner).where(
            AS2Partner.tenant_id == tenant_id, AS2Partner.id == remote_partner_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def list_as2_partners(self, tenant_id: str) -> list[AS2PartnerDomainModel]:
        stmt = select(AS2Partner).where(AS2Partner.tenant_id == tenant_id)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def get_as2_partners_by_ids(
        self, tenant_id: str, partner_ids: list[str]
    ) -> list[AS2PartnerDomainModel]:
        stmt = select(AS2Partner).where(
            AS2Partner.tenant_id == tenant_id, AS2Partner.id.in_(partner_ids)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def is_vault_ref_in_use(self, tenant_id: str, vault_ref: str) -> bool:
        stmt = select(AS2Partner).where(
            AS2Partner.tenant_id == tenant_id, AS2Partner.private_key_vault_ref == vault_ref
        )
        return (await self.session.execute(stmt)).scalars().first() is not None

    @staticmethod
    def _to_domain_model(record: AS2Partner) -> AS2PartnerDomainModel:
        return AS2PartnerDomainModel(
            id=record.id,
            as2_id=record.as2_id,
            name=record.name,
            is_local=record.is_local,
            created_at=record.created_at,
            updated_at=record.updated_at,
            tenant_id=record.tenant_id,
            public_cert_pem=record.public_cert_pem,
            public_cert_vault_ref=record.public_cert_vault_ref,
            private_key_vault_ref=record.private_key_vault_ref,
            prev_public_cert_pem=record.prev_public_cert_pem,
            prev_public_cert_vault_ref=record.prev_public_cert_vault_ref,
            prev_private_key_vault_ref=record.prev_private_key_vault_ref,
            url=record.url,
            active=record.active,
        )
