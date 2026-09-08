import os
from datetime import UTC, datetime, timedelta

import pytest
from database.router import DatabaseRouter
from edi.adapters.outbound.database.models.control_plane import ControlPlaneOutbox
from outbox.application.outbox_cleaner_use_case import (
    OutboxCleanerUseCase,
)
from outbox.domain.constants import OutboxStatus
from sqlalchemy import select

from edi_cp_cleanup.adapters.outbound.database.postgres_edi_control_plane_outbox_cleanup_repository import (
    SqlAlchemyEdiControlPlaneOutboxCleanupRepository,
)

pytestmark = pytest.mark.integration


@pytest.mark.integration
async def test_edi_control_plane_outbox_cleanup(db_router: DatabaseRouter) -> None:

    old_date = datetime.now(UTC) - timedelta(days=15)
    recent_date = datetime.now(UTC) - timedelta(days=1)

    async for test_session in db_router.get_global_session():
        ob1_id = f"cp_edi_ob_{os.urandom(12).hex()}"
        ob2_id = f"cp_edi_ob_{os.urandom(12).hex()}"
        ob3_id = f"cp_edi_ob_{os.urandom(12).hex()}"

        # Add old processed (should be deleted)
        ob1 = ControlPlaneOutbox(
            id=ob1_id,
            tenant_id="tenant-1",
            idempotency_key=f"iam_key_{os.urandom(12).hex()}",
            status=OutboxStatus.PROCESSED.value,
            event_type="TEST",
            payload={},
            created_at=old_date,
            updated_at=old_date,
        )
        # Add old pending (should NOT be deleted)
        ob2 = ControlPlaneOutbox(
            id=ob2_id,
            tenant_id="tenant-1",
            idempotency_key=f"iam_key_{os.urandom(12).hex()}",
            status=OutboxStatus.PENDING.value,
            event_type="TEST",
            payload={},
            created_at=old_date,
            updated_at=old_date,
        )
        # Add recent processed (should NOT be deleted)
        ob3 = ControlPlaneOutbox(
            id=ob3_id,
            tenant_id="tenant-1",
            idempotency_key=f"iam_key_{os.urandom(12).hex()}",
            status=OutboxStatus.PROCESSED.value,
            event_type="TEST",
            payload={},
            created_at=recent_date,
            updated_at=recent_date,
        )
        test_session.add_all([ob1, ob2, ob3])
        await test_session.commit()

    repo = SqlAlchemyEdiControlPlaneOutboxCleanupRepository(db_router)
    use_case = OutboxCleanerUseCase(repository=repo, retention_days=14)
    await use_case.execute()

    async for test_session in db_router.get_global_session():
        result = await test_session.execute(select(ControlPlaneOutbox.id))
        remaining = {r for (r,) in result.all()}

        assert ob1_id not in remaining
        assert ob2_id in remaining
        assert ob3_id in remaining
