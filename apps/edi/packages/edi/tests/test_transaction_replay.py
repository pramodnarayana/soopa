from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from edi.application.use_cases.transaction_service import TransactionService


@pytest.mark.asyncio
async def test_replay_queues_validated_transaction():
    uow = AsyncMock()
    uow.transactions.get_transaction.return_value = SimpleNamespace(edi_message=object())
    service = TransactionService(uow)

    await service.replay_transaction("tenant-1", "trace-1", "raw")

    uow.transactions.publish_outbox_event.assert_awaited_once()
    kwargs = uow.transactions.publish_outbox_event.await_args.kwargs
    assert kwargs["payload"] == {"trace_id": "trace-1", "tier": "raw"}


@pytest.mark.asyncio
async def test_bulk_replay_queues_each_unique_validated_transaction():
    uow = AsyncMock()
    uow.transactions.get_existing_trace_ids.return_value = {"trace-1", "trace-2"}
    service = TransactionService(uow)

    count = await service.bulk_replay_transactions(
        "tenant-1", ["trace-1", "trace-2", "trace-1"], "raw", command_key="command-1"
    )

    assert count == 2
    assert uow.transactions.publish_outbox_event.await_count == 2
    assert {
        call.kwargs["idempotency_key"]
        for call in uow.transactions.publish_outbox_event.await_args_list
    } == {"replay_command-1_trace-1", "replay_command-1_trace-2"}
