import pytest
from database.router import DatabaseRouterPort
from edi.adapters.outbound.database.tenant_resolver import TenantResolver
from seedwork import generate_id
from sqlalchemy import text
from ucp_models.sharding import DatabaseShard, ShardRegistry
from ucp_models.subscriptions import App


@pytest.mark.integration
async def test_tenant_resolver_success(test_db_router: DatabaseRouterPort) -> None:
    db_router = test_db_router
    test_tenant_id = generate_id("t")

    # Insert actual test data into the real global DB
    async for session in db_router.get_global_session():
        # Shard requires a DatabaseShard row first (typically seeded, but we'll ensure one exists)
        # Using a dummy shard name just for this test
        shard_name = f"shard_{test_tenant_id}"
        edi_app = App(slug="edi", name="EDI", description="EDI application")
        shard = DatabaseShard(
            id=generate_id("ucp_shard"),
            name=shard_name,
            dsn="postgresql://user:pass@host/db",
        )
        session.add_all([edi_app, shard])
        await session.flush()
        session.add(ShardRegistry(tenant_id=test_tenant_id, app_id=edi_app.id, shard_id=shard.id))
        await session.commit()

    resolver = TenantResolver(db_router=db_router, ttl_secs=300)

    # First resolve should hit DB
    shard_name, shard_dsn = await resolver.resolve(tenant_id=test_tenant_id)
    assert shard_name == f"shard_{test_tenant_id}"
    assert shard_dsn == "postgresql://user:pass@host/db"

    # Second resolve should hit cache
    # We test this by deleting the record from DB and seeing if it still resolves!
    async for session in db_router.get_global_session():
        # Clean up so a real DB query would fail
        await session.execute(
            text("DELETE FROM platform_global.shard_registry WHERE tenant_id = :tenant_id"),
            {"tenant_id": test_tenant_id},
        )
        await session.commit()

    shard_name_2, shard_dsn_2 = await resolver.resolve(tenant_id=test_tenant_id)
    assert shard_name_2 == f"shard_{test_tenant_id}"
    assert shard_dsn_2 == "postgresql://user:pass@host/db"


@pytest.mark.integration
async def test_tenant_resolver_not_found(test_db_router: DatabaseRouterPort) -> None:
    db_router = test_db_router
    resolver = TenantResolver(db_router=db_router, ttl_secs=300)

    with pytest.raises(ValueError, match="Tenant 999 not found in Global DB"):
        await resolver.resolve(tenant_id="999")


@pytest.mark.integration
async def test_tenant_resolver_eviction(test_db_router: DatabaseRouterPort) -> None:
    db_router = test_db_router

    # Small cache size to force eviction
    resolver = TenantResolver(db_router=db_router, ttl_secs=300, max_entries=2)

    # Insert 3 tenants
    t1, t2, t3 = generate_id("t1"), generate_id("t2"), generate_id("t3")
    async for session in db_router.get_global_session():
        edi_app = App(slug="edi", name="EDI", description="EDI application")
        shard1 = DatabaseShard(id=generate_id("ucp_shard"), name=f"shard_{t1}", dsn="dsn1")
        shard2 = DatabaseShard(id=generate_id("ucp_shard"), name=f"shard_{t2}", dsn="dsn2")
        shard3 = DatabaseShard(id=generate_id("ucp_shard"), name=f"shard_{t3}", dsn="dsn3")
        session.add_all([edi_app, shard1, shard2, shard3])
        await session.flush()

        session.add(ShardRegistry(tenant_id=t1, app_id=edi_app.id, shard_id=shard1.id))
        session.add(ShardRegistry(tenant_id=t2, app_id=edi_app.id, shard_id=shard2.id))
        session.add(ShardRegistry(tenant_id=t3, app_id=edi_app.id, shard_id=shard3.id))
        await session.commit()

    await resolver.resolve(tenant_id=t1)
    await resolver.resolve(tenant_id=t2)
    # This should evict t1 or t2
    await resolver.resolve(tenant_id=t3)

    assert len(resolver._cache) == 2
