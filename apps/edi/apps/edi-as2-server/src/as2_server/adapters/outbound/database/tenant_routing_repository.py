from database.models.identity import Tenant
from edi.adapters.outbound.database.models.control_plane import AS2Partner, InboundRoute
from edi.adapters.outbound.database.models.control_plane import AS2Partner as GlobalTradingPartner
from sqlalchemy import select as sql_select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.sharding import DatabaseShard


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
        self,
        as2_peer_id: str,
        isa_sender: str,
        isa_receiver: str,
        transaction_type: str | None = None,
    ) -> str | None:

        conditions = [
            InboundRoute.isa_sender_id == isa_sender,
            InboundRoute.isa_receiver_id == isa_receiver,
            InboundRoute.active.is_(True),
            AS2Partner.as2_id == as2_peer_id,
        ]
        if transaction_type:
            conditions.append(InboundRoute.transaction_type.in_([transaction_type, "*"]))

        stmt = (
            sql_select(InboundRoute.tenant_id)
            .join(AS2Partner, InboundRoute.as2_partner_id == AS2Partner.id)
            .where(*conditions)
        )
        result = await self.session.execute(stmt)
        tenant_rows = result.fetchall()
        if len(tenant_rows) > 1:
            raise ValueError(
                f"Ambiguous inbound route match: multiple tenants for ISA {isa_sender}/{isa_receiver}"
            )
        if tenant_rows:
            return str(tenant_rows[0][0])
        return None

    async def get_tenant_shard_info(self, tenant_id: str) -> tuple[str, str, str] | None:
        stmt = sql_select(Tenant, DatabaseShard).join(DatabaseShard).where(Tenant.id == tenant_id)
        row = (await self.session.execute(stmt)).first()
        if not row:
            return None
        tenant, shard = row
        return str(tenant.id), str(shard.shard_key), str(shard.connection_url)
