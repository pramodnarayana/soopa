from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from edi.application.use_cases.transactions.bulk_replay_transactions_use_case import (
    BulkReplayTransactionsUseCase,
)
from edi.application.use_cases.transactions.replay_transaction_use_case import (
    ReplayTransactionUseCase,
)


@pytest.mark.asyncio
async def test_replay_queues_validated_transaction():
    uow = AsyncMock()
    uow.transactions.get_transaction.return_value = SimpleNamespace(edi_message=object())
    service = ReplayTransactionUseCase(uow)

    await service.replay_transaction("tenant-1", "trace-1", "raw")

    uow.transactions.publish_outbox_event.assert_awaited_once()
    kwargs = uow.transactions.publish_outbox_event.await_args.kwargs
    assert kwargs["payload"] == {"trace_id": "trace-1", "tier": "raw"}


@pytest.mark.asyncio
async def test_bulk_replay_queues_each_unique_validated_transaction():
    uow = AsyncMock()
    uow.transactions.get_transaction.return_value = SimpleNamespace(edi_message=object())
    service = BulkReplayTransactionsUseCase(uow)

    count = await service.bulk_replay_transactions(
        "tenant-1", ["trace-1", "trace-2", "trace-1"], "raw", command_key="command-1"
    )

    assert count == 3
    assert uow.transactions.publish_outbox_event.await_count == 3
    assert {
        call.kwargs["idempotency_key"]
        for call in uow.transactions.publish_outbox_event.await_args_list
    } == {"bulk_replay_command-1_0", "bulk_replay_command-1_1", "bulk_replay_command-1_2"}
