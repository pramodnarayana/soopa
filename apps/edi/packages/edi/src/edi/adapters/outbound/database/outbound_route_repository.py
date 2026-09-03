import dataclasses
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from identity.domain.identity_context import PLATFORM_TENANT_ID
from seedwork.domain.types import UnsetType
from sqlalchemy import select, update

from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.control_plane import (
    AS2Partner,
    OutboundRoute,
    SFTPPartner,
)
from edi.domain.models.outbound_routes import OutboundRouteDomainModel
from edi.ports.outbound.outbound_route_repository import OutboundRouteRepositoryPort


class SqlAlchemyOutboundRouteRepository(OutboundRouteRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    @staticmethod
    def _to_domain_model(record: Any) -> OutboundRouteDomainModel:
        return OutboundRouteDomainModel(
            id=record.id,
            tenant_id=record.tenant_id,
            trading_partner_id=record.trading_partner_id,
            name=record.name,
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            protocol=getattr(record, "protocol", None),
            as2_partner_id=record.as2_partner_id,
            sftp_partner_id=record.sftp_partner_id,
        )

    async def get_outbound_route(
        self, tenant_id: str, route_id: str
    ) -> OutboundRouteDomainModel | None:
        stmt = select(OutboundRoute).where(
            OutboundRoute.id == route_id,
            OutboundRoute.tenant_id == tenant_id,
            OutboundRoute.deleted_at.is_(None),
        )
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        return self._to_domain_model(record) if record else None

    async def get_outbound_route_by_trading_partner_id(
        self, tenant_id: str, trading_partner_id: str
    ) -> OutboundRouteDomainModel | None:
        result = await self.session.execute(
            select(OutboundRoute).where(
                OutboundRoute.tenant_id == tenant_id,
                OutboundRoute.trading_partner_id == trading_partner_id,
                OutboundRoute.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        return self._to_domain_model(record) if record else None

    async def _validate_outbound_destination(
        self,
        tenant_id: str,
        as2_id: str | UUID | UnsetType | None,
        sftp_id: str | UUID | UnsetType | None,
    ) -> None:
        destinations = [
            d for d in (as2_id, sftp_id) if d is not None and not isinstance(d, UnsetType)
        ]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (as2 or sftp) must be provided")

        if as2_id:
            result = await self.session.execute(
                select(AS2Partner.id).where(
                    AS2Partner.id == as2_id,
                    AS2Partner.tenant_id.in_([tenant_id, PLATFORM_TENANT_ID]),
                    AS2Partner.active.is_(True),
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"AS2 partner {as2_id} not found or does not belong to this tenant"
                )

        if sftp_id:
            result = await self.session.execute(
                select(SFTPPartner.id).where(
                    SFTPPartner.id == sftp_id,
                    SFTPPartner.tenant_id == tenant_id,
                    SFTPPartner.deleted_at.is_(None),
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"SFTP partner {sftp_id} not found or does not belong to this tenant"
                )

    async def save(self, aggregate: OutboundRouteDomainModel) -> None:
        await self._validate_outbound_destination(
            aggregate.tenant_id, aggregate.as2_partner_id, aggregate.sftp_partner_id
        )

        result = await self.session.execute(
            select(OutboundRoute).where(
                OutboundRoute.id == aggregate.id,
                OutboundRoute.tenant_id == aggregate.tenant_id,
                OutboundRoute.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            record = OutboundRoute(id=aggregate.id)
            self.session.add(record)

        for field in dataclasses.fields(aggregate):
            if field.name not in ("created_at", "updated_at", "_domain_events"):
                setattr(record, field.name, getattr(aggregate, field.name))

        self._drain_events(aggregate)
        await self.session.flush()

    async def delete(self, aggregate: OutboundRouteDomainModel) -> None:
        await self.session.execute(
            update(OutboundRoute)
            .where(
                OutboundRoute.id == aggregate.id,
                OutboundRoute.tenant_id == aggregate.tenant_id,
                OutboundRoute.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC).replace(tzinfo=None), active=False)
        )

        self._drain_events(aggregate)
        await self.session.flush()

    async def list_outbound_routes(self, tenant_id: str) -> list[OutboundRouteDomainModel]:
        outbound_result = await self.session.execute(
            select(OutboundRoute).where(
                OutboundRoute.tenant_id == tenant_id, OutboundRoute.deleted_at.is_(None)
            )
        )
        return [self._to_domain_model(record) for record in outbound_result.scalars().all()]
