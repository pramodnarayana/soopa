from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.data_plane.exceptions import ReadOnlyDataPlaneRepositoryError
from edi.adapters.outbound.database.models.data_plane import OutboundRoute
from edi.domain.enums import EdiConnectionType
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort


class SqlAlchemyDataPlaneOutboundRouteRepository(OutboundRouteRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: OutboundRouteDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: OutboundRouteDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_outbound_route_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundRouteDomainModel | None:
        stmt = select(OutboundRoute).where(
            OutboundRoute.tenant_id == tenant_id,
            OutboundRoute.trading_partner_id == trading_partner_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_outbound_route(
        self, tenant_id: str, route_id: str
    ) -> OutboundRouteDomainModel | None:
        stmt = select(OutboundRoute).where(
            OutboundRoute.tenant_id == tenant_id, OutboundRoute.id == route_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def list_outbound_routes(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> Sequence[OutboundRouteDomainModel]:
        stmt = (
            select(OutboundRoute)
            .where(OutboundRoute.tenant_id == tenant_id)
            .limit(limit)
            .offset(offset)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: OutboundRoute) -> OutboundRouteDomainModel:
        return OutboundRouteDomainModel(
            id=record.id,
            tenant_id=record.tenant_id,
            trading_partner_id=record.trading_partner_id,
            name=record.name,
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            connection_type=EdiConnectionType(record.connection_type)
            if record.connection_type
            else None,
            as2_partner_id=record.as2_partner_id,
            sftp_partner_id=record.sftp_partner_id,
        )
