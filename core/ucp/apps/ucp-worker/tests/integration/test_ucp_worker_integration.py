import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from database.provider import get_async_engine
from seedwork import generate_random_hex
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ucp.domain.constants import UcpEventType

from ucp_worker.bootstrap.container import WorkerContainer


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine() -> AsyncGenerator[Any, None]:
    db_url = os.getenv(
        "DATABASE_URL", "postgresql+asyncpg://ucp_admin:ucp_password@localhost:5432/ucp_global"
    )
    if db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = get_async_engine(db_url)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_connection(db_engine) -> AsyncGenerator[Any, None]:
    connection = await db_engine.connect()
    transaction = await connection.begin()
    yield connection
    await transaction.rollback()
    await connection.close()


@pytest_asyncio.fixture(scope="function")
async def db_session_factory(db_connection) -> AsyncGenerator[async_sessionmaker, None]:
    factory = async_sessionmaker(
        bind=db_connection,
        expire_on_commit=False,
        class_=AsyncSession,
        join_transaction_mode="create_savepoint",
    )
    yield factory


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ucp_worker_handles_tenant_deleted_event(
    db_connection: Any, db_session_factory: async_sessionmaker
) -> None:
    # 1. Setup DB Data
    tenant_id = f"ten_del_{generate_random_hex(6)}"
    role_id = f"role_{generate_random_hex(6)}"

    # Insert a tenant and a role directly on the connection
    await db_connection.execute(
        text(
            "INSERT INTO identity.tenants (id, name, slug, status, idp_tenant_id, created_at, updated_at) VALUES (:id, 'To Delete', :slug, 'active', 'idp_123', NOW(), NOW())"
        ),
        {"id": tenant_id, "slug": f"delete-me-{generate_random_hex(6)}"},
    )
    await db_connection.execute(
        text(
            "INSERT INTO identity.roles (id, name, description, capabilities, tenant_id, created_at, updated_at) VALUES (:role_id, 'Role', '', '{}', :tenant_id, NOW(), NOW())"
        ),
        {"role_id": role_id, "tenant_id": tenant_id},
    )
    await db_connection.execute(text("SAVEPOINT seed_complete"))

    # 2. Setup Worker Container
    container = WorkerContainer()
    container.session_factory = db_session_factory
    container.settings.sqs_ucp_identity_sync_queue_url = "http://dummy"
    container.wire()

    # 3. Construct Payload
    payload = {
        "id": f"evt_{generate_random_hex(6)}",
        "event_type": UcpEventType.TENANT_DELETED.value,
        "tenant_id": tenant_id,
        "payload": {"tenant_id": tenant_id},
        "idempotency_key": f"test_idemp_{generate_random_hex(6)}",
    }

    # 4. Dispatch directly to bypass SQS connection polling and threading issues in tests
    await container.events_dispatcher.dispatch_raw(payload)

    # 5. Verify Soft Deletion
    async with db_session_factory() as session:
        res = await session.execute(
            text("SELECT deleted_at FROM identity.roles WHERE id = :role_id"), {"role_id": role_id}
        )
        deleted_at = res.scalar_one_or_none()

    await container.dispose()

    assert deleted_at is not None, "Tenant infrastructure (role) was not soft-deleted by the worker"
    print("\n\n>>> TEST FINISHED <<<\n\n")
