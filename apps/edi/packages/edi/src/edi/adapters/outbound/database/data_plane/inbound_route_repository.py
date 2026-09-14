from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.data_plane.exceptions import ReadOnlyDataPlaneRepositoryError
from edi.adapters.outbound.database.models.data_plane import InboundRoute
from edi.domain.constants import WILDCARD_TRANSACTION_TYPE
from edi.domain.enums import EdiConnectionType
from edi.domain.models.base import ProcessingMode
from edi.domain.models.inbound_routes import InboundRouteDomainModel
from edi.ports.outbound.inbound_route_repository import InboundRouteRepositoryPort


class SqlAlchemyDataPlaneInboundRouteRepository(InboundRouteRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def save(self, aggregate: InboundRouteDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def delete(self, aggregate: InboundRouteDomainModel) -> None:
        raise ReadOnlyDataPlaneRepositoryError("Data Plane configs are read-only")

    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: str,
        transaction_type: str | None = None,
    ) -> InboundRouteDomainModel | None:
        stmt = select(InboundRoute).where(
            InboundRoute.tenant_id == tenant_id,
            InboundRoute.isa_sender_id == isa_sender_id,
            InboundRoute.isa_receiver_id == isa_receiver_id,
            InboundRoute.active,
        )
        if transaction_type:
            stmt = stmt.where(
                (InboundRoute.transaction_type == transaction_type)
                | (InboundRoute.transaction_type == WILDCARD_TRANSACTION_TYPE)
            ).order_by((InboundRoute.transaction_type == transaction_type).desc())
        else:
            stmt = stmt.where(InboundRoute.transaction_type.is_(None))

        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_inbound_route_by_id(
        self, tenant_id: str, route_id: str
    ) -> InboundRouteDomainModel | None:
        stmt = select(InboundRoute).where(
            InboundRoute.tenant_id == tenant_id, InboundRoute.id == route_id
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_tenant_by_isa(self, isa_sender_id: str, isa_receiver_id: str) -> str | None:
        # Not applicable for a data plane scoped to a tenant
        raise ReadOnlyDataPlaneRepositoryError(
            "Cannot resolve tenant from tenant-scoped data plane"
        )

    async def list_inbound_routes(self, tenant_id: str) -> list[InboundRouteDomainModel]:
        stmt = select(InboundRoute).where(InboundRoute.tenant_id == tenant_id)
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    @staticmethod
    def _to_domain_model(record: InboundRoute) -> InboundRouteDomainModel:
        return InboundRouteDomainModel(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            isa_sender_id=record.isa_sender_id,
            isa_receiver_id=record.isa_receiver_id,
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            trading_partner_id=record.trading_partner_id,
            gs_sender_id=record.gs_sender_id,
            gs_receiver_id=record.gs_receiver_id,
            transaction_type=record.transaction_type,
            processing_mode=ProcessingMode(record.processing_mode)
            if record.processing_mode
            else None,
            webhook_id=record.webhook_id,
            as2_partner_id=record.as2_partner_id,
            sftp_partner_id=record.sftp_partner_id,
            connection_type=EdiConnectionType(record.connection_type)
            if record.connection_type
            else None,
        )
