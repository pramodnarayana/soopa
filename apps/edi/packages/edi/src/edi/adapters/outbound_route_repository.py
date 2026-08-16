from datetime import UTC, datetime

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.models.control_plane import (
    AS2Partner,
    OutboundRoute,
    SFTPPartner,
)
from domain.models import OutboundRouteDomainModel
from identity.domain.identity_context import PLATFORM_TENANT_ID
from sqlalchemy import select, update

from edi.domain.models import (
    UNSET,
    CreateOutboundRouteCmd,
    UnsetType,
    UpdateOutboundRouteCmd,
)
from edi.ports.outbound_route_repository import OutboundRouteRepositoryPort


class SqlAlchemyOutboundRouteRepository(OutboundRouteRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

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
        return OutboundRouteDomainModel.model_validate(record) if record else None

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
        return OutboundRouteDomainModel.model_validate(record) if record else None

    async def _validate_outbound_destination(
        self, tenant_id: str, as2_id: str | None, sftp_id: str | None
    ) -> None:
        destinations = [d for d in (as2_id, sftp_id) if d is not None]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (as2 or sftp) must be provided")

        if as2_id:
            result = await self.session.execute(
                select(AS2Partner.id).where(
                    AS2Partner.id == as2_id,
                    AS2Partner.tenant_id.in_([tenant_id, PLATFORM_TENANT_ID]),
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

    async def create_outbound_route(self, tenant_id: str, cmd: CreateOutboundRouteCmd) -> str:
        await self._validate_outbound_destination(
            tenant_id, cmd.as2_partner_id, cmd.sftp_partner_id
        )

        record_route = OutboundRoute(
            tenant_id=tenant_id,
            trading_partner_id=cmd.trading_partner_id,
            name=cmd.name,
            as2_partner_id=cmd.as2_partner_id,
            sftp_partner_id=cmd.sftp_partner_id,
        )
        self.session.add(record_route)
        await self.session.flush()
        return record_route.id

    async def update_outbound_route(
        self, tenant_id: str, route_id: str, cmd: UpdateOutboundRouteCmd
    ) -> bool:
        result = await self.session.execute(
            select(OutboundRoute).where(
                OutboundRoute.id == route_id,
                OutboundRoute.tenant_id == tenant_id,
                OutboundRoute.deleted_at.is_(None),
            )
        )
        record_route = result.scalar_one_or_none()
        if not record_route:
            return False

        if cmd.trading_partner_id is not UNSET:
            record_route.trading_partner_id = cmd.trading_partner_id
        if not isinstance(cmd.name, UnsetType):
            record_route.name = cmd.name

        if not isinstance(cmd.as2_partner_id, UnsetType):
            record_route.as2_partner_id = cmd.as2_partner_id
        if not isinstance(cmd.sftp_partner_id, UnsetType):
            record_route.sftp_partner_id = cmd.sftp_partner_id
        if not isinstance(cmd.active, UnsetType):
            record_route.active = cmd.active

        await self._validate_outbound_destination(
            tenant_id, record_route.as2_partner_id, record_route.sftp_partner_id
        )

        await self.session.flush()
        return True

    async def delete_outbound_route(self, tenant_id: str, route_id: str) -> bool:
        result = await self.session.execute(
            update(OutboundRoute)
            .where(
                OutboundRoute.id == route_id,
                OutboundRoute.tenant_id == tenant_id,
                OutboundRoute.deleted_at.is_(None),
            )
            .values(deleted_at=datetime.now(UTC).replace(tzinfo=None), active=False)
        )
        await self.session.flush()
        return bool(getattr(result, "rowcount", 0) > 0)

    async def list_outbound_routes(self, tenant_id: str) -> list[OutboundRouteDomainModel]:
        outbound_result = await self.session.execute(
            select(OutboundRoute).where(
                OutboundRoute.tenant_id == tenant_id, OutboundRoute.deleted_at.is_(None)
            )
        )
        return [OutboundRouteDomainModel.model_validate(r) for r in outbound_result.scalars().all()]
