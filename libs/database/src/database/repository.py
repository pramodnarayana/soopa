from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models.control_plane import AS2Partner
from .models.data_plane import EdiMessage


class TradingPartnerRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def find_by_as2_id(self, tenant_id: int, as2_id: str) -> AS2Partner | None:

        result = await self.session.execute(
            select(AS2Partner).where(
                AS2Partner.as2_id == as2_id,
                AS2Partner.tenant_id == tenant_id,
                AS2Partner.active.is_(True),
            )
        )
        return result.scalar_one_or_none()


class PartnershipRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_partnership_by_as2_ids(
        self, as2_from: str, as2_to: str
    ) -> tuple[Any, Any, Any] | None:
        from sqlalchemy import func
        from sqlalchemy.orm import aliased

        from .models.control_plane import AS2Partnership

        LocalPartner = aliased(AS2Partner)
        RemotePartner = aliased(AS2Partner)

        stmt = (
            select(AS2Partnership, LocalPartner, RemotePartner)
            .join(LocalPartner, AS2Partnership.local_partner_id == LocalPartner.id)
            .join(RemotePartner, AS2Partnership.remote_partner_id == RemotePartner.id)
            .where(
                func.lower(LocalPartner.as2_id) == as2_to.lower(),
                func.lower(RemotePartner.as2_id) == as2_from.lower(),
                AS2Partnership.active.is_(True),
                LocalPartner.active.is_(True),
                RemotePartner.active.is_(True),
            )
        )

        result = await self.session.execute(stmt)
        row = result.first()
        if not row:
            return None

        return row[0], row[1], row[2]


class InboundRouteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_inbound_route(
        self,
        isa_sender_id: str,
        isa_receiver_id: str,
        tenant_id: int | None = None,
        transaction_type: str | None = None,
    ) -> Any | None:
        from .models.control_plane import InboundRoute

        conditions = [
            InboundRoute.isa_sender_id == isa_sender_id,
            InboundRoute.isa_receiver_id == isa_receiver_id,
            InboundRoute.active.is_(True),
        ]
        if tenant_id is not None and tenant_id != 0:
            conditions.append(InboundRoute.tenant_id == tenant_id)
        if transaction_type:
            conditions.append(InboundRoute.transaction_type == transaction_type)

        stmt = select(InboundRoute).where(*conditions).order_by(InboundRoute.id).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class EdiMessageRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # removed _tenant_id

    async def save_message(
        self,
        tenant_id: int,
        trace_id: UUID,
        direction: str,
        connection_type: str,
        edi_data: str,
        sender_id: str | None = None,
        receiver_id: str | None = None,
        status: str = "RECEIVED",
        message_id: str | None = None,
    ) -> EdiMessage:
        record = EdiMessage(
            tenant_id=tenant_id,
            trace_id=trace_id,
            direction=direction,
            connection_type=connection_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            edi_data=edi_data,
            status=status,
            message_id=message_id,
        )
        self.session.add(record)
        await self.session.flush()
        return record
