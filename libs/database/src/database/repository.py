from uuid import UUID

from identity.tenant_context import get_tenant_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models.control_plane import AS2Partner
from .models.data_plane import EdiMessage


class TradingPartnerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_as2_id(self, as2_id: str) -> AS2Partner | None:
        """Finds an AS2 partner globally across all tenants."""
        result = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.as2_id == as2_id,
                AS2Partner.active.is_(True),
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
        trace_id: UUID,
        direction: str,
        connection_type: str,
        s3_key: str,
        sender_id: str | None = None,
        receiver_id: str | None = None,
        status: str = "RECEIVED",
        as2_message_id: str | None = None,
    ) -> EdiMessage:
        record = EdiMessage(
            tenant_id=self._tenant_id(),
            trace_id=trace_id,
            direction=direction,
            connection_type=connection_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            s3_key=s3_key,
            status=status,
            as2_message_id=as2_message_id,
        )
        self.session.add(record)
        await self.session.flush()
        return record
