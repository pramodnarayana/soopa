from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from edi.adapters.outbound.database.data_plane.exceptions import ReadOnlyDataPlaneRepositoryError
from edi.adapters.outbound.database.data_plane.mappers import as2_partner_to_domain
from edi.adapters.outbound.database.models.data_plane import AS2Partner as OrmAS2Partner
from edi.adapters.outbound.database.models.data_plane import AS2Partnership as OrmAS2Partnership
from edi.domain.partner.as2.partner import AS2Partner
from edi.domain.partner.as2.partnership import AS2Partnership
from edi.ports.outbound.as2_partnership_repository import AS2PartnershipRepositoryPort


class SqlAlchemyDataPlaneAS2PartnershipRepository(AS2PartnershipRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: AS2Partnership) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: AS2Partnership) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_as2_partnership(
        self, tenant_id: str, partnership_id: str
    ) -> AS2Partnership | None:
        stmt = select(OrmAS2Partnership).where(
            OrmAS2Partnership.tenant_id == PLATFORM_TENANT_ID,
            OrmAS2Partnership.id == partnership_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[AS2Partnership, AS2Partner, AS2Partner] | None:
        LocalPartner = aliased(OrmAS2Partner)
        RemotePartner = aliased(OrmAS2Partner)

        stmt = (
            select(OrmAS2Partnership, RemotePartner, LocalPartner)
            .join(LocalPartner, OrmAS2Partnership.local_partner_id == LocalPartner.id)
            .join(RemotePartner, OrmAS2Partnership.remote_partner_id == RemotePartner.id)
            .where(
                OrmAS2Partnership.tenant_id == PLATFORM_TENANT_ID,
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
            as2_partner_to_domain(sender_record),
            as2_partner_to_domain(receiver_record),
        )

    async def get_as2_partnership_by_identifiers(
        self, tenant_id: str, local_partner_id: str, remote_partner_id: str
    ) -> AS2Partnership | None:
        stmt = select(OrmAS2Partnership).where(
            OrmAS2Partnership.tenant_id == PLATFORM_TENANT_ID,
            OrmAS2Partnership.local_partner_id == local_partner_id,
            OrmAS2Partnership.remote_partner_id == remote_partner_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_as2_partnerships_by_remote_partner_id(
        self, tenant_id: str, remote_partner_id: str, active: bool | None = None
    ) -> list[AS2Partnership]:
        stmt = select(OrmAS2Partnership).where(
            OrmAS2Partnership.tenant_id == PLATFORM_TENANT_ID,
            OrmAS2Partnership.remote_partner_id == remote_partner_id,
        )
        if active is not None:
            stmt = stmt.where(OrmAS2Partnership.active.is_(active))
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def list_as2_partnerships(self, tenant_id: str) -> list[AS2Partnership]:
        stmt = select(OrmAS2Partnership).where(OrmAS2Partnership.tenant_id == PLATFORM_TENANT_ID)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: OrmAS2Partnership) -> AS2Partnership:
        return AS2Partnership(
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
