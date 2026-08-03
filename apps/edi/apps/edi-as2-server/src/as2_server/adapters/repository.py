import uuid

from database.models.control_plane import AS2Partner as GlobalTradingPartner
from database.repository import EdiMessageRepository as DbEdiMessageRepository
from database.repository import TradingPartnerRepository as DbTradingPartnerRepository
from sqlalchemy import select as sql_select
from sqlalchemy.ext.asyncio import AsyncSession

from ..ports.repository import PartnerEntity


class AS2TenantRepositoryAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve_tenant_id(self, as2_to: str) -> str | None:
        result = await self.session.execute(
            sql_select(GlobalTradingPartner.tenant_id)
            .where(GlobalTradingPartner.as2_id == as2_to)
            .where(GlobalTradingPartner.is_local.is_(True))
            .where(GlobalTradingPartner.active.is_(True))
        )
        tenant_rows = result.fetchall()
        if len(tenant_rows) > 1:
            raise ValueError(f"Ambiguous AS2-To match: multiple tenants claim {as2_to}")
        if tenant_rows:
            return str(tenant_rows[0][0])
        return None

    async def resolve_tenant_by_edi_identifiers(
        self, isa_sender: str, isa_receiver: str
    ) -> str | None:
        from database.models.control_plane import InboundRoute

        result = await self.session.execute(
            sql_select(InboundRoute.tenant_id)
            .where(InboundRoute.isa_sender_id == isa_sender)
            .where(InboundRoute.isa_receiver_id == isa_receiver)
            .where(InboundRoute.active.is_(True))
            .limit(1)
        )
        tenant_id = result.scalar_one_or_none()
        if tenant_id:
            return str(tenant_id)
        return None


class TradingPartnerRepositoryAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = DbTradingPartnerRepository(session)

    async def find_by_as2_id(self, tenant_id: str, as2_id: str) -> PartnerEntity | None:
        partner = await self.repo.find_by_as2_id(tenant_id, as2_id)
        if not partner:
            return None
        return PartnerEntity(as2_id=partner.as2_id, public_cert_pem=partner.public_cert_pem)


class EdiMessageRepositoryAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = DbEdiMessageRepository(session)

    async def save_message(
        self,
        tenant_id: str,
        trace_id: uuid.UUID,
        direction: str,
        connection_type: str,
        sender_id: str,
        receiver_id: str,
        edi_data: str,
        status: str,
        as2_message_id: str,
    ) -> None:
        await self.repo.save_message(
            tenant_id=tenant_id,
            trace_id=trace_id,
            direction=direction,
            connection_type=connection_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            edi_data=edi_data,
            status=status,
            message_id=as2_message_id,
        )
