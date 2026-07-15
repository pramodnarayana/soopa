import uuid
from collections.abc import Sequence
from uuid import UUID

from api.domain.models import (
    UNSET,
    CreateOutboundEdiHeaderCmd,
    CreateOutboundRouteCmd,
    UnsetType,
    UpdateOutboundEdiHeaderCmd,
    UpdateOutboundRouteCmd,
)
from api.ports.outbound_route_repository import OutboundRouteRepositoryPort
from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.models.control_plane import (
    AS2Partner,
    InboundRoute,
    OutboundEdiHeader,
    OutboundRoute,
    SFTPPartner,
)
from domain.models import InboundRouteDomainModel, OutboundRouteDomainModel
from sqlalchemy import delete, select


class SqlAlchemyOutboundRouteRepository(OutboundRouteRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def get_outbound_route(
        self, tenant_id: int, route_id: UUID
    ) -> OutboundRouteDomainModel | None:
        stmt = select(OutboundRoute).where(
            OutboundRoute.id == route_id, OutboundRoute.tenant_id == tenant_id
        )
        res = await self.session.execute(stmt)
        record = res.scalar_one_or_none()
        return OutboundRouteDomainModel.model_validate(record) if record else None

    async def get_outbound_route_by_trading_partner_id(
        self, tenant_id: int, trading_partner_id: str
    ) -> OutboundRouteDomainModel | None:
        result = await self.session.execute(
            select(OutboundRoute).where(
                OutboundRoute.tenant_id == tenant_id,
                OutboundRoute.trading_partner_id == trading_partner_id,
            )
        )
        record = result.scalar_one_or_none()
        return OutboundRouteDomainModel.model_validate(record) if record else None

    async def create_outbound_route(self, tenant_id: int, cmd: CreateOutboundRouteCmd) -> UUID:
        destinations = [d for d in (cmd.as2_partner_id, cmd.sftp_partner_id) if d is not None]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (as2 or sftp) must be provided")

        if cmd.as2_partner_id:
            result = await self.session.execute(
                select(AS2Partner.id).where(
                    AS2Partner.id == cmd.as2_partner_id,
                    AS2Partner.tenant_id.in_([tenant_id, 0]),
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"AS2 partner {cmd.as2_partner_id} not found or does not belong to this tenant"
                )

        if cmd.sftp_partner_id:
            result = await self.session.execute(
                select(SFTPPartner.id).where(
                    SFTPPartner.id == cmd.sftp_partner_id, SFTPPartner.tenant_id == tenant_id
                )
            )
            if not result.scalar_one_or_none():
                raise ValueError(
                    f"SFTP partner {cmd.sftp_partner_id} not found or does not belong to this tenant"
                )

        route_id = uuid.uuid4()
        record_route = OutboundRoute(
            id=route_id,
            tenant_id=tenant_id,
            trading_partner_id=cmd.trading_partner_id,
            name=cmd.name,
            as2_partner_id=cmd.as2_partner_id,
            sftp_partner_id=cmd.sftp_partner_id,
        )
        self.session.add(record_route)
        await self.session.flush()
        return route_id

    async def update_outbound_route(
        self, tenant_id: int, route_id: UUID, cmd: UpdateOutboundRouteCmd
    ) -> bool:
        result = await self.session.execute(
            select(OutboundRoute).where(
                OutboundRoute.id == route_id, OutboundRoute.tenant_id == tenant_id
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
            if cmd.as2_partner_id is not None:
                r = await self.session.execute(
                    select(AS2Partner.id).where(
                        AS2Partner.id == cmd.as2_partner_id,
                        AS2Partner.tenant_id.in_([tenant_id, 0]),
                    )
                )
                if not r.scalar_one_or_none():
                    raise ValueError("AS2 partner not found")
            record_route.as2_partner_id = cmd.as2_partner_id
        if not isinstance(cmd.sftp_partner_id, UnsetType):
            if cmd.sftp_partner_id is not None:
                r = await self.session.execute(
                    select(SFTPPartner.id).where(
                        SFTPPartner.id == cmd.sftp_partner_id, SFTPPartner.tenant_id == tenant_id
                    )
                )
                if not r.scalar_one_or_none():
                    raise ValueError("SFTP partner not found")
            record_route.sftp_partner_id = cmd.sftp_partner_id
        if not isinstance(cmd.active, UnsetType):
            record_route.active = cmd.active

        destinations = [
            d for d in (record_route.as2_partner_id, record_route.sftp_partner_id) if d is not None
        ]
        if len(destinations) != 1:
            raise ValueError("Exactly one destination (as2 or sftp) must be provided")

        await self.session.flush()
        return True

    async def delete_outbound_route(self, tenant_id: int, route_id: UUID) -> bool:
        result = await self.session.execute(
            delete(OutboundRoute).where(
                OutboundRoute.id == route_id, OutboundRoute.tenant_id == tenant_id
            )
        )
        await self.session.flush()
        return bool(getattr(result, "rowcount", 0) > 0)

    async def create_outbound_edi_header(
        self, tenant_id: int, cmd: CreateOutboundEdiHeaderCmd
    ) -> UUID:
        header_id = uuid.uuid4()
        record = OutboundEdiHeader(
            id=header_id,
            tenant_id=tenant_id,
            name=cmd.name,
            trading_partner_id=cmd.trading_partner_id,
            isa_sender_id=cmd.isa_sender_id,
            isa_receiver_id=cmd.isa_receiver_id,
            gs_sender_id=cmd.gs_sender_id,
            gs_receiver_id=cmd.gs_receiver_id,
            transaction_type=cmd.transaction_type,
            isa_sender_qualifier=cmd.isa_sender_qualifier,
            isa_receiver_qualifier=cmd.isa_receiver_qualifier,
            default_standard=cmd.default_standard,
            default_version=cmd.default_version,
        )
        self.session.add(record)
        await self.session.flush()
        return header_id

    async def update_outbound_edi_header(
        self, tenant_id: int, header_id: UUID, cmd: UpdateOutboundEdiHeaderCmd
    ) -> bool:
        result = await self.session.execute(
            select(OutboundEdiHeader).where(
                OutboundEdiHeader.id == header_id, OutboundEdiHeader.tenant_id == tenant_id
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return False
        if not isinstance(cmd.name, UnsetType):
            record.name = cmd.name
        if not isinstance(cmd.trading_partner_id, UnsetType):
            record.trading_partner_id = cmd.trading_partner_id
        if not isinstance(cmd.isa_sender_id, UnsetType):
            record.isa_sender_id = cmd.isa_sender_id
        if not isinstance(cmd.isa_sender_qualifier, UnsetType):
            record.isa_sender_qualifier = cmd.isa_sender_qualifier
        if not isinstance(cmd.isa_receiver_id, UnsetType):
            record.isa_receiver_id = cmd.isa_receiver_id
        if not isinstance(cmd.isa_receiver_qualifier, UnsetType):
            record.isa_receiver_qualifier = cmd.isa_receiver_qualifier
        if not isinstance(cmd.gs_sender_id, UnsetType):
            record.gs_sender_id = cmd.gs_sender_id
        if not isinstance(cmd.gs_receiver_id, UnsetType):
            record.gs_receiver_id = cmd.gs_receiver_id
        if not isinstance(cmd.transaction_type, UnsetType):
            record.transaction_type = cmd.transaction_type
        if not isinstance(cmd.default_standard, UnsetType):
            record.default_standard = cmd.default_standard
        if not isinstance(cmd.default_version, UnsetType):
            record.default_version = cmd.default_version
        await self.session.flush()
        return True

    async def delete_outbound_edi_header(self, tenant_id: int, header_id: UUID) -> bool:
        result = await self.session.execute(
            delete(OutboundEdiHeader).where(
                OutboundEdiHeader.id == header_id, OutboundEdiHeader.tenant_id == tenant_id
            )
        )
        await self.session.flush()
        return bool(getattr(result, "rowcount", 0) > 0)

    async def get_outbound_edi_headers(self, tenant_id: int) -> Sequence[OutboundEdiHeader]:
        result = await self.session.execute(
            select(OutboundEdiHeader).where(OutboundEdiHeader.tenant_id == tenant_id)
        )
        return result.scalars().all()

    async def get_outbound_edi_header_by_trading_partner_id(
        self, tenant_id: int, trading_partner_id: str
    ) -> OutboundEdiHeader | None:
        result = await self.session.execute(
            select(OutboundEdiHeader).where(
                OutboundEdiHeader.tenant_id == tenant_id,
                OutboundEdiHeader.trading_partner_id == trading_partner_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_all_routes(
        self, tenant_id: int
    ) -> dict[str, list[OutboundRouteDomainModel | InboundRouteDomainModel]]:
        inbound_result = await self.session.execute(
            select(InboundRoute).where(InboundRoute.tenant_id == tenant_id)
        )
        outbound_result = await self.session.execute(
            select(OutboundRoute).where(OutboundRoute.tenant_id == tenant_id)
        )

        inbound_routes = [
            InboundRouteDomainModel.model_validate(r) for r in inbound_result.scalars().all()
        ]
        outbound_routes = [
            OutboundRouteDomainModel.model_validate(r) for r in outbound_result.scalars().all()
        ]

        return {"inbound": inbound_routes, "outbound": outbound_routes}  # type: ignore
