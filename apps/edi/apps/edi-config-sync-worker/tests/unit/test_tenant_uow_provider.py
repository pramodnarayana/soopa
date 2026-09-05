import pytest
from database.router import DatabaseRouterPort
from edi.adapters.outbound.database.tenant_resolver import TenantResolver
from edi.adapters.outbound.database.tenant_uow_provider import TenantUowProvider
from edi.adapters.outbound.database.uow_adapter import (
    SqlAlchemyDataPlaneUnitOfWork,
)
from edi.config.settings import get_settings
from seedwork import generate_id
from ucp_models.infrastructure import DatabaseShard, ShardRegistry


@pytest.mark.integration
async def test_tenant_uow_provider_success(db_router: DatabaseRouterPort) -> None:
    """Test that TenantUowProvider resolves tenant and yields a DataPlaneUnitOfWorkPort."""
    test_tenant_id = generate_id("t")
    shard_name = f"shard_{test_tenant_id}"

    # 1. Setup Data - real tenant in real db
    async for session in db_router.get_global_session():
        session.add(
            DatabaseShard(
                name=shard_name,
                dsn="postgresql+asyncpg://postgres:postgres@localhost:5432/platform_db",
            )
        )
        session.add(ShardRegistry(tenant_id=test_tenant_id, shard_name=shard_name))
        await session.commit()

    # 2. Use Real components
    real_resolver = TenantResolver(db_router=db_router, ttl_secs=300)
    real_settings = get_settings()

    provider = TenantUowProvider(
        resolver=real_resolver,
        db_router=db_router,
        settings=real_settings,
        s3_bucket="fake-bucket",
        aws_endpoint=None,
    )

    # 3. Execute
    uow_factory = await provider.get_uow_factory(test_tenant_id)

    # 4. Verify it creates a real SQL Alchemy UOW
    async with uow_factory() as uow:
        assert isinstance(uow, SqlAlchemyDataPlaneUnitOfWork)
        # Should be able to execute a dummy query on the tenant session
        from sqlalchemy import text

        res = await uow._session.execute(text("SELECT 1"))
        assert res.scalar() == 1
