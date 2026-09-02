from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Webhook
from edi.adapters.outbound.database.models.control_plane import AS2Partner, SFTPPartner
from edi.adapters.outbound.database.models.data_plane import InboundRoute, OutboundRoute
from edi.domain.models.base import ConnectionType
from edi.ports.outbound.routing_resolver_repository import RoutingResolverRepositoryPort


class SqlAlchemyRoutingResolverRepository(RoutingResolverRepositoryPort):
    def __init__(self, global_session: AsyncSession, tenant_session: AsyncSession | None):
        self.global_session = global_session
        self.tenant_session = tenant_session

    async def resolve_outbound_route(
        self, trading_partner_id: str
    ) -> tuple[str, ConnectionType] | None:
        if not self.tenant_session:
            return None

        route = (
            await self.tenant_session.execute(
                select(OutboundRoute).where(
                    OutboundRoute.trading_partner_id == trading_partner_id,
                    OutboundRoute.active.is_(True),
                )
            )
        ).scalar_one_or_none()

        if route:
            if route.as2_partner_id:
                res = await self.global_session.execute(
                    select(AS2Partner.name).where(AS2Partner.id == route.as2_partner_id)
                )
                name = res.scalar_one_or_none()
                if name:
                    return name, ConnectionType.AS2

            if route.sftp_partner_id:
                res = await self.global_session.execute(
                    select(SFTPPartner.name).where(SFTPPartner.id == route.sftp_partner_id)
                )
                name = res.scalar_one_or_none()
                if name:
                    return name, ConnectionType.SFTP
        return None

    async def resolve_as2_inbound(self, as2_from: str) -> tuple[str, ConnectionType] | None:
        res = await self.global_session.execute(
            select(AS2Partner.name).where(AS2Partner.as2_id == as2_from)
        )
        name = res.scalar_one_or_none()
        if name:
            return name, ConnectionType.AS2
        return None

    async def resolve_inbound_route(
        self, sender_id: str, receiver_id: str, transaction_type: str | None
    ) -> tuple[str, ConnectionType] | None:
        if not self.tenant_session:
            return None

        stmt = select(InboundRoute).where(
            InboundRoute.isa_sender_id == sender_id,
            InboundRoute.isa_receiver_id == receiver_id,
            InboundRoute.active.is_(True),
        )
        if transaction_type:
            stmt = stmt.where(InboundRoute.transaction_type == transaction_type)

        inbound_route = (await self.tenant_session.execute(stmt)).scalars().first()
        if inbound_route:
            if inbound_route.sftp_partner_id:
                res = await self.global_session.execute(
                    select(SFTPPartner.name).where(SFTPPartner.id == inbound_route.sftp_partner_id)
                )
                name = res.scalar_one_or_none()
                if name:
                    return name, ConnectionType.SFTP

            elif inbound_route.webhook_id:
                res = await self.global_session.execute(
                    select(Webhook.url).where(Webhook.id == inbound_route.webhook_id)
                )
                webhook_url = res.scalar_one_or_none()
                if webhook_url:
                    return webhook_url, ConnectionType.WEBHOOK
        return None

    async def resolve_business_metadata(self, partner_ids: list[str]) -> str | None:
        if not partner_ids:
            return None

        res = await self.global_session.execute(
            select(AS2Partner.name).where(AS2Partner.id.in_(partner_ids))
        )
        name = res.scalars().first()
        if name:
            return name

        res = await self.global_session.execute(
            select(SFTPPartner.name).where(SFTPPartner.id.in_(partner_ids))
        )
        name = res.scalars().first()
        if name:
            return name

        return None
