import uuid
from typing import Any
from uuid import UUID

from api.domain.models import CreateTradingPartnerRequest
from api.ports.repository import ControlPlaneRepositoryPort
from database.models.control_plane import (
    Connection as GlobalConnection,
)
from database.models.control_plane import (
    Outbox as GlobalOutbox,
)
from database.models.control_plane import (
    TradingPartner as GlobalTradingPartner,
)
from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyControlPlaneRepository(ControlPlaneRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_trading_partner(
        self, tenant_id: int, partner_name: str, as2_id: str | None, direction: str
    ) -> UUID:
        partner_id = uuid.uuid4()
        record = GlobalTradingPartner(
            id=partner_id,
            tenant_id=tenant_id,
            partner_name=partner_name,
            as2_id=as2_id,
            direction=direction,
            provision_status="PROVISIONING",
            active=True,
        )
        self.session.add(record)
        await self.session.flush()
        return partner_id

    async def create_connection(
        self, trading_partner_id: UUID, tenant_id: int, request: CreateTradingPartnerRequest
    ) -> UUID:
        conn_id = uuid.uuid4()
        directions = ["INBOUND", "OUTBOUND"] if request.direction == "BOTH" else [request.direction]
        first_inserted_id = None

        for dir_val in directions:
            current_id = conn_id if len(directions) == 1 else uuid.uuid4()
            if first_inserted_id is None:
                first_inserted_id = current_id
            record = GlobalConnection(
                id=current_id,
                trading_partner_id=trading_partner_id,
                tenant_id=tenant_id,
                connection_type=request.connection_type,
                host=request.host,
                port=request.port,
                direction=dir_val,
                credentials_vault_ref=request.credentials_vault_ref,
                active=True,
            )
            self.session.add(record)

        await self.session.flush()
        return first_inserted_id if first_inserted_id else conn_id

    async def create_outbox_event(
        self, tenant_id: int, event_type: str, payload: dict[str, Any]
    ) -> UUID:
        event_id = uuid.uuid4()
        record = GlobalOutbox(
            id=event_id,
            tenant_id=tenant_id,
            idempotency_key=uuid.uuid4(),
            event_type=event_type,
            payload=payload,
            status="PENDING",
        )
        self.session.add(record)
        await self.session.flush()
        return event_id
