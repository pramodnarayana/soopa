from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from edi.adapters.outbound.database.data_plane.as2_partner_repository import (
    SqlAlchemyDataPlaneAS2PartnerRepository,
)
from edi.adapters.outbound.database.data_plane.exceptions import ReadOnlyDataPlaneRepositoryError
from edi.adapters.outbound.database.models.data_plane import AS2Partner, AS2Partnership
from edi.domain.models.as2 import AS2PartnerDomainModel, AS2PartnershipDomainModel
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort


class SqlAlchemyDataPlaneAS2PartnershipRepository(AS2PartnershipRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: AS2PartnershipDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: AS2PartnershipDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_as2_partnership(
        self, tenant_id: str, partnership_id: str
    ) -> AS2PartnershipDomainModel | None:
        stmt = select(AS2Partnership).where(
            AS2Partnership.tenant_id == PLATFORM_TENANT_ID, AS2Partnership.id == partnership_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2PartnershipDomainModel, AS2PartnerDomainModel, AS2PartnerDomainModel] | None:
        LocalPartner = aliased(AS2Partner)
        RemotePartner = aliased(AS2Partner)

        stmt = (
            select(AS2Partnership, RemotePartner, LocalPartner)
            .join(LocalPartner, AS2Partnership.local_partner_id == LocalPartner.id)
            .join(RemotePartner, AS2Partnership.remote_partner_id == RemotePartner.id)
            .where(
                AS2Partnership.tenant_id == PLATFORM_TENANT_ID,
                func.lower(LocalPartner.as2_id) == as2_to.lower(),
                func.lower(RemotePartner.as2_id) == as2_from.lower(),
            )
        )
        row = (await self.session.execute(stmt)).first()
        if not row:
            return None
        partnership_record, sender_record, receiver_record = row
        return (
            self._to_domain_model(partnership_record),
            SqlAlchemyDataPlaneAS2PartnerRepository._to_domain_model(sender_record),
            SqlAlchemyDataPlaneAS2PartnerRepository._to_domain_model(receiver_record),
        )

    async def get_as2_partnership_by_identifiers(
        self, tenant_id: str, local_partner_id: str, remote_partner_id: str
    ) -> AS2PartnershipDomainModel | None:
        stmt = select(AS2Partnership).where(
            AS2Partnership.tenant_id == PLATFORM_TENANT_ID,
            AS2Partnership.local_partner_id == local_partner_id,
            AS2Partnership.remote_partner_id == remote_partner_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_as2_partnerships_by_remote_partner_id(
        self, tenant_id: str, remote_partner_id: str, active: bool | None = None
    ) -> list[AS2PartnershipDomainModel]:
        stmt = select(AS2Partnership).where(
            AS2Partnership.tenant_id == PLATFORM_TENANT_ID,
            AS2Partnership.remote_partner_id == remote_partner_id,
        )
        if active is not None:
            stmt = stmt.where(AS2Partnership.active.is_(active))
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def list_as2_partnerships(self, tenant_id: str) -> list[AS2PartnershipDomainModel]:
        stmt = select(AS2Partnership).where(AS2Partnership.tenant_id == PLATFORM_TENANT_ID)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: AS2Partnership) -> AS2PartnershipDomainModel:
        return AS2PartnershipDomainModel(
            id=record.id,
            name=record.name,
            local_partner_id=record.local_partner_id,
            remote_partner_id=record.remote_partner_id,
            mdn_type=record.mdn_type,
            encryption_algorithm=record.encryption_algorithm,
            signature_algorithm=record.signature_algorithm,
            created_at=record.created_at,
            updated_at=record.updated_at,
            tenant_id=record.tenant_id,
            credentials_vault_ref=record.credentials_vault_ref,
            mdn_url=record.mdn_url,
            advanced_flags=record.advanced_flags,
            active=record.active,
        )
