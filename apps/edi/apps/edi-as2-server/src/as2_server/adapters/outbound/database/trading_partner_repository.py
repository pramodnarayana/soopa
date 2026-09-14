from edi.adapters.outbound.database.models.control_plane import AS2Partner
from sqlalchemy import select as sql_select
from sqlalchemy.ext.asyncio import AsyncSession

from as2_server.ports.outbound.repository_port import PartnerEntity


class TradingPartnerRepositoryAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_as2_id(self, tenant_id: str, as2_id: str) -> PartnerEntity | None:
        result = await self.session.execute(
            sql_select(AS2Partner).where(
                AS2Partner.as2_id == as2_id,
                AS2Partner.tenant_id == tenant_id,
                AS2Partner.active.is_(True),
            )
        )
        partner = result.scalar_one_or_none()
        if not partner:
            return None
        return PartnerEntity(
            as2_id=partner.as2_id, public_cert_pem=partner.public_cert_pem, active=partner.active
        )
