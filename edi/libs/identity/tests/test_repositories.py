import os
from collections.abc import AsyncGenerator

import pytest
from database.connection import DatabaseRouter
from database.models import Tenant, User
from identity.infrastructure.repositories import SQLAlchemyIdentityRepository
from sqlalchemy import select

GLOBAL_DB_URL = os.getenv(
    "DB_GLOBAL_URL", "postgresql+asyncpg://edi:edi_password@localhost:5432/edi_global"
)


@pytest.fixture
async def router() -> AsyncGenerator[DatabaseRouter, None]:
    db_router = DatabaseRouter(GLOBAL_DB_URL, pool_size=2, max_overflow=2)
    yield db_router
    await db_router.close_all()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sqlalchemy_identity_repository_jit_provision(router: DatabaseRouter) -> None:
    async_gen = router.get_global_session()
    session = await async_gen.__anext__()
    created_user = None
    created_tenant = None
    try:
        import uuid

        test_email = f"jit_{uuid.uuid4().hex[:8]}@example.com"

        # Ensure default shard exists
        from database.models.control_plane import DatabaseShard
        from sqlalchemy.dialects.postgresql import insert

        stmt = insert(DatabaseShard).values(
            name="shard_1",
            dsn="postgresql+asyncpg://edi:edi_password@localhost:5433/edi_shard_1",
        )
        stmt = stmt.on_conflict_do_update(index_elements=["name"], set_={"dsn": stmt.excluded.dsn})
        await session.execute(stmt)
        await session.flush()

        repo = SQLAlchemyIdentityRepository(session)
        tenant_id = await repo.provision_tenant_for_user(test_email, "JIT User")

        # Verify
        assert tenant_id is not None

        user_stmt = select(User).where(User.email == test_email)
        created_user = (await session.execute(user_stmt)).scalar_one()
        assert created_user.name == "JIT User"

        tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
        created_tenant = (await session.execute(tenant_stmt)).scalar_one()
        assert "JIT User's Organization" in created_tenant.name
        assert created_tenant.shard_id is not None
        assert created_tenant.shard_schema.startswith("tenant_")

    finally:
        # Cleanup: explicitly delete created records since provision_tenant_for_user() commits
        try:
            if created_user is not None:
                # Delete TenantUser mapping first (foreign key constraint)
                from database.models import TenantUser

                tenant_user_stmt = select(TenantUser).where(TenantUser.user_id == created_user.id)
                tenant_user = (await session.execute(tenant_user_stmt)).scalar_one_or_none()
                if tenant_user:
                    await session.delete(tenant_user)

                # Delete Tenant
                if created_tenant is not None:
                    await session.delete(created_tenant)

                # Delete User
                await session.delete(created_user)

                await session.commit()
        except Exception:
            # If cleanup fails, rollback as fallback
            await session.rollback()
        finally:
            await session.rollback()
            import contextlib

            with contextlib.suppress(StopAsyncIteration):
                await async_gen.__anext__()
