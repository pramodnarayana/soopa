from identity.tenant_context import get_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EdiMessage, TenantConnection, TenantTradingPartner


class TradingPartnerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _tenant_id(self) -> int:
        tenant_id = get_tenant_id()
        if tenant_id is None:
            raise RuntimeError("Database queries require an active tenant context.")
        return tenant_id

    async def find_by_as2_id(self, as2_id: str) -> TenantTradingPartner | None:
        result = await self.session.execute(
            select(TenantTradingPartner).where(
                TenantTradingPartner.tenant_id == self._tenant_id(),
                TenantTradingPartner.as2_id == as2_id,
                TenantTradingPartner.active.is_(True),
            )
        )
        return result.scalar_one_or_none()


class ConnectionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _tenant_id(self) -> int:
        tenant_id = get_tenant_id()
        if tenant_id is None:
            raise RuntimeError("Database queries require an active tenant context.")
        return tenant_id

    async def find_by_partner_id(
        self, partner_id: str, connection_type: str
    ) -> TenantConnection | None:
        result = await self.session.execute(
            select(TenantConnection).where(
                TenantConnection.tenant_id == self._tenant_id(),
                TenantConnection.trading_partner_id == partner_id,
                TenantConnection.connection_type == connection_type,
                TenantConnection.active.is_(True),
            )
        )
        return result.scalar_one_or_none()


class EdiMessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    def _tenant_id(self) -> int:
        tenant_id = get_tenant_id()
        if tenant_id is None:
            raise RuntimeError("Database queries require an active tenant context.")
        return tenant_id

    async def save_message(
        self,
        trace_id: str,
        direction: str,
        connection_type: str,
        trading_partner_id: str,
        s3_key: str,
        status: str = "RECEIVED",
    ) -> EdiMessage:
        record = EdiMessage(
            tenant_id=self._tenant_id(),
            trace_id=trace_id,
            direction=direction,
            connection_type=connection_type,
            trading_partner_id=trading_partner_id,
            s3_key=s3_key,
            status=status,
        )
        self.session.add(record)
        await self.session.flush()
        return record
