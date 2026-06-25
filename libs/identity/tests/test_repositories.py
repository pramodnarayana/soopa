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
    try:
        import uuid

        test_email = f"jit_{uuid.uuid4().hex[:8]}@example.com"
        repo = SQLAlchemyIdentityRepository(session)
        tenant_id = await repo.provision_tenant_for_user(test_email, "JIT User")

        # Verify
        assert tenant_id is not None

        user_stmt = select(User).where(User.email == test_email)
        user = (await session.execute(user_stmt)).scalar_one()
        assert user.name == "JIT User"

        tenant_stmt = select(Tenant).where(Tenant.id == tenant_id)
        tenant = (await session.execute(tenant_stmt)).scalar_one()
        assert "JIT User's Organization" in tenant.name

        # Cleanup
        await session.rollback()
    finally:
        await session.rollback()
        import contextlib

        with contextlib.suppress(StopAsyncIteration):
            await async_gen.__anext__()
