import pytest
from database.testing import TransactionalTestRouter
from sqlalchemy import text

from worker.adapters.db_tenant import SqlAlchemyTenantAdapter


@pytest.mark.integration
async def test_get_all_tenant_ids(db_router: TransactionalTestRouter) -> None:
    # 1. Setup adapter
    adapter = SqlAlchemyTenantAdapter(db_router=db_router)

    tenant_id = "test_tenant_xyz"
    app_id = "test_app_xyz"
    shard_id = "test_shard_xyz"

    # Seed Tenant
    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) VALUES (:id, :name, :slug, 'active', NOW(), NOW())"
        ),
        {"id": tenant_id, "name": "Test Tenant", "slug": "test_tenant"},
    )
    # Seed App (slug must be EDI_APP_SLUG = 'edi')
    app_id_result = await db_router.global_conn.execute(
        text(
            "INSERT INTO ucp.apps (id, name, slug, created_at, updated_at) VALUES (:id, :name, 'edi', NOW(), NOW()) ON CONFLICT (slug) DO UPDATE SET updated_at = NOW() RETURNING id"
        ),
        {"id": app_id, "name": "EDI App"},
    )
    real_app_id = app_id_result.scalar_one()
    # Seed DatabaseShard
    await db_router.global_conn.execute(
        text(
            "INSERT INTO ucp.database_shards (id, name, dsn, status, created_at, updated_at) VALUES (:id, :name, :dsn, 'active', NOW(), NOW())"
        ),
        {"id": shard_id, "name": "test_edi_shard_1", "dsn": "postgres://..."},
    )
    # Seed ShardRegistry
    await db_router.global_conn.execute(
        text(
            "INSERT INTO ucp.shard_registry (tenant_id, app_id, shard_id, status, created_at, updated_at) VALUES (:tenant_id, :app_id, :shard_id, 'active', NOW(), NOW())"
        ),
        {"tenant_id": tenant_id, "app_id": real_app_id, "shard_id": shard_id},
    )

    # 3. Call method
    tenant_ids = await adapter.get_all_tenant_ids()

    # 4. Verify
    assert tenant_id in tenant_ids


@pytest.mark.integration
async def test_resolve_shard(db_router: TransactionalTestRouter) -> None:
    # 1. Setup adapter
    adapter = SqlAlchemyTenantAdapter(db_router=db_router)

    tenant_id = "test_tenant_abc"
    app_id = "test_app_abc"
    shard_id = "test_shard_abc"
    shard_name = "test_edi_shard_2"
    shard_dsn = "postgres://test-dsn"

    await db_router.global_conn.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, created_at, updated_at) VALUES (:id, :name, :slug, 'active', NOW(), NOW())"
        ),
        {"id": tenant_id, "name": "Test Tenant 2", "slug": "test_tenant_2"},
    )
    # Seed App (slug must be EDI_APP_SLUG = 'edi')
    app_id_result = await db_router.global_conn.execute(
        text(
            "INSERT INTO ucp.apps (id, name, slug, created_at, updated_at) VALUES (:id, :name, 'edi', NOW(), NOW()) ON CONFLICT (slug) DO UPDATE SET updated_at = NOW() RETURNING id"
        ),
        {"id": app_id, "name": "EDI App 2"},
    )
    real_app_id = app_id_result.scalar_one()
    await db_router.global_conn.execute(
        text(
            "INSERT INTO ucp.database_shards (id, name, dsn, status, created_at, updated_at) VALUES (:id, :name, :dsn, 'active', NOW(), NOW())"
        ),
        {"id": shard_id, "name": shard_name, "dsn": shard_dsn},
    )
    await db_router.global_conn.execute(
        text(
            "INSERT INTO ucp.shard_registry (tenant_id, app_id, shard_id, status, created_at, updated_at) VALUES (:tenant_id, :app_id, :shard_id, 'active', NOW(), NOW())"
        ),
        {"tenant_id": tenant_id, "app_id": real_app_id, "shard_id": shard_id},
    )

    # 3. Call method
    resolved_name, resolved_dsn = await adapter.resolve_shard(tenant_id)

    # 4. Verify
    assert resolved_name == shard_name
    assert resolved_dsn == shard_dsn
