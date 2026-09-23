import pytest

pytestmark = pytest.mark.integration

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.base_repository import TenantSession
from edi.adapters.outbound.database.data_plane.uow import SqlAlchemyDataPlaneUnitOfWork
from edi.adapters.outbound.database.models.data_plane import ProcessedEvent
from edi.testing.fakes.pipeline_fakes import InMemoryStorageAdapter


@pytest.fixture
async def uow(db_session: AsyncSession) -> SqlAlchemyDataPlaneUnitOfWork:
    """Provides a fresh DataPlaneUnitOfWork instance with an active test transaction."""
    conn = await db_session.connection()
    await conn.run_sync(ProcessedEvent.metadata.create_all)

    db_session.info["session_type"] = "tenant"
    tenant_session = TenantSession(db_session)
    return SqlAlchemyDataPlaneUnitOfWork(
        tenant_session=tenant_session, storage=InMemoryStorageAdapter()
    )


@pytest.mark.asyncio
async def test_record_idempotency_success_when_new(
    uow: SqlAlchemyDataPlaneUnitOfWork, db_session: AsyncSession
) -> None:
    # Arrange
    tenant_id = "tenant-test-123"
    idempotency_key = "some_success_key_1"

    # Act
    is_new = await uow.record_idempotency(tenant_id, idempotency_key)

    # Assert
    assert is_new is True

    # Verify the record actually got inserted (flush required if check inside transaction)
    await db_session.flush()
    result = await db_session.execute(
        sa.select(ProcessedEvent).where(
            ProcessedEvent.tenant_id == tenant_id,
            ProcessedEvent.idempotency_key == idempotency_key,
        )
    )
    record = result.scalars().first()
    assert record is not None
    assert record.idempotency_key == idempotency_key


@pytest.mark.asyncio
async def test_record_idempotency_fails_when_duplicate(
    uow: SqlAlchemyDataPlaneUnitOfWork, db_session: AsyncSession
) -> None:
    # Arrange
    tenant_id = "tenant-test-456"
    idempotency_key = "some_duplicate_key_1"

    # Insert first time
    is_new_first = await uow.record_idempotency(tenant_id, idempotency_key)
    assert is_new_first is True

    # Act - Insert second time within same transaction (or next)
    is_new_second = await uow.record_idempotency(tenant_id, idempotency_key)

    # Assert - should be False
    assert is_new_second is False


@pytest.mark.asyncio
async def test_record_idempotency_empty_args(
    uow: SqlAlchemyDataPlaneUnitOfWork,
) -> None:
    # Act
    result1 = await uow.record_idempotency("", "some_key")
    result2 = await uow.record_idempotency("tenant_id", "")

    # Assert - should return True but bypass insertion
    assert result1 is True
    assert result2 is True
