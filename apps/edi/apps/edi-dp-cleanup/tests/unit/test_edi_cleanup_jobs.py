from typing import Any

import pytest

from edi_dp_cleanup.adapters.inbound.jobs.edi_audit_log_cleanup_job import (
    EdiAuditLogCleanupJobHandler,
)
from edi_dp_cleanup.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
    EdiDataPlaneOutboxCleanupJobHandler,
)
from edi_dp_cleanup.adapters.inbound.jobs.edi_idempotency_cleanup_job import (
    EdiIdempotencyCleanupJobHandler,
)


class FakeUseCase:
    def __init__(self) -> None:
        self.execute_count = 0
        self.should_raise = False

    async def execute(self) -> None:
        if self.should_raise:
            raise RuntimeError("DB Down")
        self.execute_count += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_class",
    [
        EdiDataPlaneOutboxCleanupJobHandler,
        EdiIdempotencyCleanupJobHandler,
        EdiAuditLogCleanupJobHandler,
    ],
)
async def test_edi_cleanup_execute(handler_class: Any) -> None:
    fake_use_case = FakeUseCase()
    handler = handler_class(use_case=fake_use_case)

    await handler.execute()

    assert fake_use_case.execute_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler_class",
    [
        EdiDataPlaneOutboxCleanupJobHandler,
        EdiIdempotencyCleanupJobHandler,
        EdiAuditLogCleanupJobHandler,
    ],
)
async def test_edi_cleanup_execute_exception_propagates(handler_class: Any) -> None:
    fake_use_case = FakeUseCase()
    fake_use_case.should_raise = True
    handler = handler_class(use_case=fake_use_case)

    with pytest.raises(RuntimeError, match="DB Down"):
        await handler.execute()
