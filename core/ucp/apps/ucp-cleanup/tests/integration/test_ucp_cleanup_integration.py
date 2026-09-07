import os
from datetime import UTC, datetime, timedelta

import pytest
from database.models.idempotency import IdempotencyResult
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.domain.constants import OutboxStatus
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from ucp.adapters.outbound.database.postgres_ucp_idempotency_cleanup_repository import (
    SqlAlchemyUcpIdempotencyCleanupRepository,
)
from ucp.adapters.outbound.database.postgres_ucp_outbox_cleanup_repository import (
    SqlAlchemyUcpOutboxCleanupRepository,
)
from ucp.application.use_cases.ucp_idempotency_cleanup_use_case import (
    UcpIdempotencyCleanupUseCase,
)
from ucp_models.events import UcpOutbox

pytestmark = pytest.mark.integration


@pytest.mark.integration
async def test_ucp_outbox_cleanup(session_factory: async_sessionmaker) -> None:
    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    ob1_id = f"ucp_cp_ob_{os.urandom(12).hex()}"
    ob2_id = f"ucp_cp_ob_{os.urandom(12).hex()}"
    ob3_id = f"ucp_cp_ob_{os.urandom(12).hex()}"

    async with session_factory() as session:
        # Add old processed (should be deleted)
        ob1 = UcpOutbox(
            id=ob1_id,
            tenant_id="test_tenant",
            idempotency_key=f"iam_key_{os.urandom(12).hex()}",
            status=OutboxStatus.PROCESSED.value,
            event_type="TEST",
            payload={},
            created_at=old_date,
            updated_at=old_date,
        )
        # Add old pending (should NOT be deleted)
        ob2 = UcpOutbox(
            id=ob2_id,
            tenant_id="test_tenant",
            idempotency_key=f"iam_key_{os.urandom(12).hex()}",
            status=OutboxStatus.PENDING.value,
            event_type="TEST",
            payload={},
            created_at=old_date,
            updated_at=old_date,
        )
        # Add recent processed (should NOT be deleted)
        ob3 = UcpOutbox(
            id=ob3_id,
            tenant_id="test_tenant",
            idempotency_key=f"iam_key_{os.urandom(12).hex()}",
            status=OutboxStatus.PROCESSED.value,
            event_type="TEST",
            payload={},
            created_at=recent_date,
            updated_at=recent_date,
        )
        session.add_all([ob1, ob2, ob3])
        await session.commit()

    repo = SqlAlchemyUcpOutboxCleanupRepository(session_factory)
    use_case = OutboxCleanerUseCase(repository=repo, retention_days=14)
    await use_case.execute()

    async with session_factory() as session:
        result = await session.execute(select(UcpOutbox.id))
        remaining = {r for (r,) in result.all()}

        assert ob1_id not in remaining
        assert ob2_id in remaining
        assert ob3_id in remaining


@pytest.mark.integration
async def test_ucp_idempotency_cleanup(session_factory: async_sessionmaker) -> None:
    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    key1 = f"iam_key_{os.urandom(12).hex()}"
    key2 = f"iam_key_{os.urandom(12).hex()}"

    async with session_factory() as session:
        ev1 = IdempotencyResult(
            tenant_id="test_tenant",
            idempotency_key=key1,
            response_status_code=200,
            response_body={},
            created_at=old_date,
            expires_at=old_date + timedelta(days=1),
        )
        ev2 = IdempotencyResult(
            tenant_id="test_tenant",
            idempotency_key=key2,
            response_status_code=200,
            response_body={},
            created_at=recent_date,
            expires_at=recent_date + timedelta(days=1),
        )
        session.add_all([ev1, ev2])
        await session.commit()

    repo = SqlAlchemyUcpIdempotencyCleanupRepository(session_factory)
    use_case = UcpIdempotencyCleanupUseCase(repository=repo, retention_days=14)
    await use_case.execute()

    async with session_factory() as session:
        result = await session.execute(select(IdempotencyResult.idempotency_key))
        remaining = {r for (r,) in result.all()}

        assert key1 not in remaining
        assert key2 in remaining
