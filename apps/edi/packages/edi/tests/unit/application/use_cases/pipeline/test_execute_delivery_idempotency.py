import contextlib
from collections.abc import AsyncIterator, Mapping
from typing import cast

import pytest

from edi.application.use_cases.pipeline.execute_delivery_use_case import (
    ExecuteDeliveryCommand,
    ExecuteDeliveryUseCase,
)
from edi.core.pipeline.delivery.base import (
    BaseDeliveryStrategy,
    TerminalDeliveryError,
    TransientDeliveryError,
)
from edi.domain.enums import EdiTraceEventType
from edi.domain.routing.enums import EdiDirection
from edi.domain.transaction.edi_message import EdiMessage
from edi.domain.transaction.enums import MessageStatus
from edi.ports.outbound.uow import DataPlaneUnitOfWorkPort
from edi.testing.fakes.pipeline_fakes import FakeDataPlaneUnitOfWork

pytestmark = pytest.mark.asyncio


class FakeDeliveryStrategySpy(BaseDeliveryStrategy):
    def __init__(
        self, should_fail_transient: bool = False, should_fail_terminal: bool = False
    ) -> None:
        self.call_count = 0
        self.should_fail_transient = should_fail_transient
        self.should_fail_terminal = should_fail_terminal

    async def deliver(
        self,
        trace_id: str,
        partner_id: str,
        edi_message: EdiMessage,
        idempotency_key: str | None = None,
    ) -> None:
        self.call_count += 1
        if self.should_fail_terminal:
            raise TerminalDeliveryError("Invalid partner configuration", code="CONFIG_ERROR")
        if self.should_fail_transient:
            raise TransientDeliveryError("Connection timed out", code="NET_TIMEOUT")


def make_use_case(
    uow: FakeDataPlaneUnitOfWork,
    strategy: BaseDeliveryStrategy,
) -> ExecuteDeliveryUseCase:
    @contextlib.asynccontextmanager
    async def uow_factory() -> AsyncIterator[DataPlaneUnitOfWorkPort]:
        yield cast(DataPlaneUnitOfWorkPort, uow)

    strategies: Mapping[str, BaseDeliveryStrategy] = {"webhook_id": strategy}
    return ExecuteDeliveryUseCase(uow_factory=uow_factory, strategies=strategies)


async def test_execute_delivery_atomic_idempotency_prevents_duplicate_network_call() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-test-1"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "tenant_id": "tenant-1",
        "direction": EdiDirection.INBOUND,
        "status": MessageStatus.PENDING_DELIVERY,
    }

    strategy = FakeDeliveryStrategySpy()
    use_case = make_use_case(uow, strategy)

    cmd = ExecuteDeliveryCommand(
        trace_id=trace_id,
        tenant_id="tenant-1",
        partner_id="wp1",
        strategy_type="webhook_id",
        connection_type="WEBHOOK",
    )

    # 1. First execution
    res1 = await use_case.execute(cmd, idempotency_key="idemp-key-1")
    assert res1 == EdiTraceEventType.DELIVERY_SUCCESSFUL
    assert strategy.call_count == 1

    # 2. Duplicate concurrent execution
    res2 = await use_case.execute(cmd, idempotency_key="idemp-key-1")
    assert res2 == EdiTraceEventType.DELIVERY_SUCCESSFUL
    # Crucial assertion: Physical delivery strategy was NOT called a second time!
    assert strategy.call_count == 1


async def test_execute_delivery_transient_error_releases_reservation_for_retry() -> None:
    uow = FakeDataPlaneUnitOfWork()
    trace_id = "trace-test-2"
    uow.repository.edi_messages[trace_id] = {
        "trace_id": trace_id,
        "tenant_id": "tenant-1",
        "direction": EdiDirection.INBOUND,
        "status": MessageStatus.PENDING_DELIVERY,
    }

    strategy = FakeDeliveryStrategySpy(should_fail_transient=True)
    use_case = make_use_case(uow, strategy)

    cmd = ExecuteDeliveryCommand(
        trace_id=trace_id,
        tenant_id="tenant-1",
        partner_id="wp1",
        strategy_type="webhook_id",
        connection_type="WEBHOOK",
    )

    # 1. Attempt fails transiently
    res1 = await use_case.execute(cmd, idempotency_key="idemp-key-2")
    assert res1 == EdiTraceEventType.DELIVERY_ATTEMPT_FAILED
    assert strategy.call_count == 1

    # 2. Fix the transient error and simulate SQS retry
    strategy.should_fail_transient = False
    res2 = await use_case.execute(cmd, idempotency_key="idemp-key-2")
    assert res2 == EdiTraceEventType.DELIVERY_SUCCESSFUL
    # Crucial assertion: Retry was permitted because transient failure released the reservation!
    assert strategy.call_count == 2
