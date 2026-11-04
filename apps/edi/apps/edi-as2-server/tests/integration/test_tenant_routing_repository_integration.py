import pytest
from database.constants import DatabaseShardStatus
from database.models.identity import Tenant
from edi.adapters.outbound.database.models.control_plane import AS2Partner, InboundRoute
from identity.domain.constants import IdentityIdPrefix
from seedwork import generate_id, generate_random_hex
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.domain.constants import LifecycleStatus
from ucp_models.sharding import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App

from as2_server.adapters.outbound.database.tenant_routing_repository import (
    SqlAlchemyTenantRoutingRepository,
)
from as2_server.domain.errors import AmbiguousTenantRoutingError

pytestmark = [pytest.mark.asyncio, pytest.mark.integration]


async def test_tenant_routing_repository_queries_against_postgres(
    global_db_session: AsyncSession,
) -> None:
    suffix = generate_random_hex(6)
    tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    second_tenant_id = generate_id(IdentityIdPrefix.TENANT.value)
    local_as2_id = f"LOCAL_STATION_{suffix}"
    remote_as2_id = f"REMOTE_PEER_{suffix}"
    shard_id = f"edi_shard_{suffix}"
    shard_dsn = "postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_test"

    tenant_one = Tenant(
        id=tenant_id,
        name=f"AS2 Routing Tenant 1 {suffix}",
        slug=f"as2-routing-1-{suffix}",
        status=LifecycleStatus.ACTIVE,
    )
    tenant_two = Tenant(
        id=second_tenant_id,
        name=f"AS2 Routing Tenant 2 {suffix}",
        slug=f"as2-routing-2-{suffix}",
        status=LifecycleStatus.ACTIVE,
    )
    global_db_session.add_all([tenant_one, tenant_two])
    await global_db_session.flush()

    app_row = await global_db_session.execute(select(App.id).where(App.slug == "edi"))
    app_id = str(app_row.scalar() or f"app_edi_{suffix}")
    if await global_db_session.get(App, app_id) is None:
        global_db_session.add(
            App(
                id=app_id,
                slug="edi",
                name="EDI Gateway",
                description="EDI Bounded Context",
            )
        )
        await global_db_session.flush()

    global_db_session.add(
        DatabaseShard(
            id=shard_id,
            name=f"EDI Test Shard {suffix}",
            dsn=shard_dsn,
            status=DatabaseShardStatus.ACTIVE,
        )
    )
    await global_db_session.flush()

    global_db_session.add(
        ShardRegistry(
            tenant_id=tenant_id,
            app_id=app_id,
            shard_id=shard_id,
        )
    )

    local_partner = AS2Partner(
        id=generate_id("as2p"),
        tenant_id=tenant_id,
        name=f"Local Station {suffix}",
        as2_id=local_as2_id,
        is_local=True,
        active=True,
    )
    remote_partner = AS2Partner(
        id=generate_id("as2p"),
        tenant_id=tenant_id,
        name=f"Remote Peer {suffix}",
        as2_id=remote_as2_id,
        is_local=False,
        active=True,
    )
    global_db_session.add_all([local_partner, remote_partner])
    await global_db_session.flush()

    route_one = InboundRoute(
        id=generate_id("route"),
        tenant_id=tenant_id,
        name=f"Inbound 850 {suffix}",
        isa_sender_id=f"SND{suffix[:6].upper()}",
        isa_receiver_id=f"RCV{suffix[:6].upper()}",
        transaction_type="850",
        as2_partner_id=remote_partner.id,
        active=True,
    )
    global_db_session.add(route_one)
    await global_db_session.flush()

    repo = SqlAlchemyTenantRoutingRepository(global_db_session)

    # 1. Direct local AS2 station resolution
    assert await repo.resolve_tenant_id(local_as2_id) == tenant_id
    assert await repo.resolve_tenant_id(f"UNKNOWN_{suffix}") is None

    # 2. EDI ISA/GS + transaction_type route resolution via SQL JOIN on AS2Partner
    resolved = await repo.resolve_tenant_by_edi_identifiers(
        as2_peer_id=remote_as2_id,
        isa_sender=route_one.isa_sender_id,
        isa_receiver=route_one.isa_receiver_id,
        transaction_type="850",
    )
    assert resolved == tenant_id

    missing_tx = await repo.resolve_tenant_by_edi_identifiers(
        as2_peer_id=remote_as2_id,
        isa_sender=route_one.isa_sender_id,
        isa_receiver=route_one.isa_receiver_id,
        transaction_type="810",
    )
    assert missing_tx is None

    # Duplicate active route across two tenants raises AmbiguousTenantRoutingError
    duplicate_route = InboundRoute(
        id=generate_id("route"),
        tenant_id=second_tenant_id,
        name=f"Duplicate Inbound 850 {suffix}",
        isa_sender_id=route_one.isa_sender_id,
        isa_receiver_id=route_one.isa_receiver_id,
        transaction_type="*",
        as2_partner_id=remote_partner.id,
        active=True,
    )
    global_db_session.add(duplicate_route)
    await global_db_session.flush()

    with pytest.raises(AmbiguousTenantRoutingError):
        await repo.resolve_tenant_by_edi_identifiers(
            as2_peer_id=remote_as2_id,
            isa_sender=route_one.isa_sender_id,
            isa_receiver=route_one.isa_receiver_id,
            transaction_type="850",
        )

    # 3. Shard lookup via Tenant -> ShardRegistry -> DatabaseShard SQL JOIN
    shard_info = await repo.get_tenant_shard_info(tenant_id)
    assert shard_info == (tenant_id, shard_id, shard_dsn)
    assert await repo.get_tenant_shard_info(f"ten_missing_{suffix}") is None
