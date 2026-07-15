from uuid import UUID

from api.ports.data_plane_as2_repository import DataPlaneAS2RepositoryPort
from database.base_repository import TenantSession, TenantSqlAlchemyRepository
from domain.models import AS2PartnerDomainModel, AS2PartnershipDomainModel
from sqlalchemy import select


class SqlAlchemyDataPlaneAS2Repository(DataPlaneAS2RepositoryPort, TenantSqlAlchemyRepository):
    def __init__(self, session: TenantSession) -> None:
        TenantSqlAlchemyRepository.__init__(self, session)

    async def get_as2_partnership(
        self, tenant_id: int, partnership_id: UUID
    ) -> AS2PartnershipDomainModel | None:
        from database.models.data_plane import AS2Partnership

        result = await self.session.execute(
            select(AS2Partnership).where(
                AS2Partnership.id == partnership_id,
                AS2Partnership.tenant_id == tenant_id,
            )
        )
        record = result.scalar_one_or_none()
        return AS2PartnershipDomainModel.model_validate(record) if record else None

    async def get_as2_partner(
        self, tenant_id: int, partner_id: UUID
    ) -> AS2PartnerDomainModel | None:
        from database.models.data_plane import AS2Partner

        result = await self.session.execute(
            select(AS2Partner).where(AS2Partner.id == partner_id, AS2Partner.tenant_id == tenant_id)
        )
        record = result.scalar_one_or_none()
        return AS2PartnerDomainModel.model_validate(record) if record else None
