import pytest
from database.testing import TransactionalTestRouter
from edi.adapters.outbound.database.models.control_plane import AS2Partner as GlobalAS2Partner
from edi.adapters.outbound.database.models.control_plane import InboundRoute as GlobalInboundRoute
from edi.adapters.outbound.database.models.data_plane import AS2Partner as TenantAS2Partner
from edi.adapters.outbound.database.models.data_plane import InboundRoute as TenantInboundRoute
from seedwork import generate_random_hex
from sqlalchemy import select, text

from worker.adapters.db_replication import SqlAlchemyReplicationAdapter
from worker.ports.outbound.tenant_port import TenantPort


class FakeTenantPort(TenantPort):
    async def get_all_tenant_ids(self) -> list[str]:
        return ["tenant_1"]

    async def resolve_shard(self, tenant_id: str) -> tuple[str, str]:
        # During tests, the TransactionalTestRouter ignores the shard connection string
        # and just yields the transaction on the primary test database, so we just
        # need to return arbitrary values here.
        return "ucp_shard_1", "fake_dsn"


@pytest.fixture
def fake_tenant_port() -> FakeTenantPort:
    return FakeTenantPort()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_replicate_as2_partner(
    db_router: TransactionalTestRouter, fake_tenant_port: FakeTenantPort
) -> None:
    # 1. Setup - Insert into global DB
    tenant_id = f"ten_orch_{generate_random_hex(6)}"
    partner_id = f"partner_{generate_random_hex(6)}"

    # We must insert a tenant first because global models typically reference it
    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) "
            "VALUES (:id, 'Test', :slug, 'active', NOW(), NOW())"
        ),
        {"id": tenant_id, "slug": f"orch-{generate_random_hex(6)}"},
    )

    # Insert AS2 Partner into global DB
    async for session in db_router.get_global_session():
        global_partner = GlobalAS2Partner(
            id=partner_id,
            tenant_id=tenant_id,
            name="Test Partner",
            as2_id="TEST_AS2_ID",
            url="http://test.com/as2",
            is_local=False,
            public_cert_pem="dummy_cert_data",
        )
        session.add(global_partner)
        await session.commit()

    # 2. Replicate
    adapter = SqlAlchemyReplicationAdapter(db_router, fake_tenant_port)
    await adapter.replicate_as2_partner(tenant_id, partner_id)

    # 3. Assert it exists in the tenant DB
    async for session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", "fake_dsn"):
        result = await session.execute(
            select(TenantAS2Partner).where(
                TenantAS2Partner.id == partner_id, TenantAS2Partner.tenant_id == tenant_id
            )
        )
        tenant_partner = result.scalars().first()

        assert tenant_partner is not None
        assert tenant_partner.name == "Test Partner"
        assert tenant_partner.as2_id == "TEST_AS2_ID"
        assert tenant_partner.url == "http://test.com/as2"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_replicate_inbound_route_with_dependency(
    db_router: TransactionalTestRouter, fake_tenant_port: FakeTenantPort
) -> None:
    """Test that granular replication automatically pulls in the FK dependencies."""
    tenant_id = f"ten_orch_{generate_random_hex(6)}"
    partner_id = f"partner_{generate_random_hex(6)}"
    route_id = f"route_{generate_random_hex(6)}"

    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) "
            "VALUES (:id, 'Test', :slug, 'active', NOW(), NOW())"
        ),
        {"id": tenant_id, "slug": f"orch-{generate_random_hex(6)}"},
    )

    async for session in db_router.get_global_session():
        global_partner = GlobalAS2Partner(
            id=partner_id,
            tenant_id=tenant_id,
            name="Dep Partner",
            as2_id="DEP_AS2_ID",
            url="http://dep.com/as2",
            is_local=True,
            public_cert_pem="dummy_cert",
        )

        global_route = GlobalInboundRoute(
            id=route_id,
            tenant_id=tenant_id,
            name="Test Route",
            isa_sender_id="SENDER1",
            isa_receiver_id="RECEIVER1",
            transaction_type="850",
            processing_mode="TRANSFORM",
            active=True,
            as2_partner_id=partner_id,
        )

        session.add(global_partner)
        session.add(global_route)
        await session.commit()

    # 2. Replicate ONLY the route. The adapter should automatically fetch and replicate the partner dependency.
    adapter = SqlAlchemyReplicationAdapter(db_router, fake_tenant_port)
    await adapter.replicate_inbound_route(tenant_id, route_id)

    # 3. Assert both route and its dependency exist in the tenant DB
    async for session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", "fake_dsn"):
        route_res = await session.execute(
            select(TenantInboundRoute).where(TenantInboundRoute.id == route_id)
        )
        tenant_route = route_res.scalars().first()

        partner_res = await session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == partner_id)
        )
        tenant_partner = partner_res.scalars().first()

        assert tenant_route is not None
        assert tenant_route.name == "Test Route"

        assert tenant_partner is not None
        assert tenant_partner.name == "Dep Partner"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_replicate_tenant_configuration_full_sync(
    db_router: TransactionalTestRouter, fake_tenant_port: FakeTenantPort
) -> None:
    """Test full topological replication driver."""
    tenant_id = f"ten_orch_{generate_random_hex(6)}"
    partner_id = f"partner_{generate_random_hex(6)}"

    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) "
            "VALUES (:id, 'Test', :slug, 'active', NOW(), NOW())"
        ),
        {"id": tenant_id, "slug": f"orch-{generate_random_hex(6)}"},
    )

    # We manually insert a partner into the tenant DB to simulate a stale record that should be deleted
    stale_partner_id = f"stale_{generate_random_hex(6)}"
    async for session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", "fake_dsn"):
        stale_partner = TenantAS2Partner(
            id=stale_partner_id,
            tenant_id=tenant_id,
            name="Stale",
            as2_id="STALE_ID",
            url="http://stale",
            is_local=False,
            public_cert_pem="x",
        )
        session.add(stale_partner)
        await session.commit()

    # We insert the real partner into the global DB
    async for session in db_router.get_global_session():
        global_partner = GlobalAS2Partner(
            id=partner_id,
            tenant_id=tenant_id,
            name="Real Partner",
            as2_id="REAL_ID",
            url="http://real",
            is_local=False,
            public_cert_pem="y",
        )
        session.add(global_partner)
        await session.commit()

    # Run full sync
    adapter = SqlAlchemyReplicationAdapter(db_router, fake_tenant_port)
    await adapter.replicate_tenant_configuration(tenant_id)

    # Assert Real Partner is there and Stale Partner is deleted
    async for session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", "fake_dsn"):
        real_res = await session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == partner_id)
        )
        assert real_res.scalars().first() is not None

        stale_res = await session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == stale_partner_id)
        )
        assert stale_res.scalars().first() is None


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_granular(
    db_router: TransactionalTestRouter, fake_tenant_port: FakeTenantPort
) -> None:
    tenant_id = f"ten_orch_{generate_random_hex(6)}"
    partner_id = f"partner_{generate_random_hex(6)}"

    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) "
            "VALUES (:id, 'Test', :slug, 'active', NOW(), NOW())"
        ),
        {"id": tenant_id, "slug": f"orch-{generate_random_hex(6)}"},
    )

    async for session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", "fake_dsn"):
        partner = TenantAS2Partner(
            id=partner_id,
            tenant_id=tenant_id,
            name="To Delete",
            as2_id="DEL_ID",
            url="http://del",
            is_local=False,
            public_cert_pem="z",
        )
        session.add(partner)
        await session.commit()

    adapter = SqlAlchemyReplicationAdapter(db_router, fake_tenant_port)
    await adapter.delete_as2_partner(tenant_id, partner_id)

    async for session in db_router.get_tenant_session(tenant_id, "ucp_shard_1", "fake_dsn"):
        res = await session.execute(
            select(TenantAS2Partner).where(TenantAS2Partner.id == partner_id)
        )
        assert res.scalars().first() is None
