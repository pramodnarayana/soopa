from typing import Any

import pytest

from edi_background_worker.adapters.inbound.jobs.edi_audit_log_cleanup_job import (
    EdiAuditLogCleanupJobHandler,
)
from edi_background_worker.adapters.inbound.jobs.edi_data_plane_outbox_cleanup_job import (
    EdiDataPlaneOutboxCleanupJobHandler,
)
from edi_background_worker.adapters.inbound.jobs.edi_idempotency_cleanup_job import (
    EdiIdempotencyCleanupJobHandler,
)
from edi_background_worker.constants import EdiJobName
from edi_background_worker.main import EdiJobDispatcher


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


@pytest.mark.asyncio
async def test_edi_job_dispatcher_routes_to_correct_handler() -> None:
    """EdiJobDispatcher.dispatch routes by job_name to the subscribed handler."""
    called_with: list[dict[str, Any]] = []

    async def fake_handler(msg: dict[str, Any]) -> None:
        called_with.append(msg)

    dispatcher = EdiJobDispatcher()
    dispatcher.subscribe(EdiJobName.EDI_DATA_PLANE_OUTBOX_SWEEPER.value, fake_handler)

    msg = {"job_name": EdiJobName.EDI_DATA_PLANE_OUTBOX_SWEEPER.value}
    await dispatcher.dispatch(msg)

    assert len(called_with) == 1
    assert called_with[0] is msg


@pytest.mark.asyncio
async def test_edi_job_dispatcher_raises_on_unknown_job_name() -> None:
    dispatcher = EdiJobDispatcher()

    with pytest.raises(ValueError, match="Unknown EDI job name: unknown_job"):
        await dispatcher.dispatch({"job_name": "unknown_job"})
