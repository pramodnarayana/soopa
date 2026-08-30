from unittest.mock import AsyncMock

import pytest

from scheduler_worker.adapters.inbound.workers.scheduler_poller import SchedulerPoller


@pytest.fixture
def mock_sweep_use_case():
    return AsyncMock()


@pytest.fixture
def mock_claim_use_case():
    return AsyncMock()


@pytest.mark.asyncio
async def test_scheduler_poller_init(mock_sweep_use_case, mock_claim_use_case):
    poller = SchedulerPoller(
        sweep_use_case=mock_sweep_use_case,
        claim_use_case=mock_claim_use_case,
        worker_id="test_worker_1",
        poll_interval_seconds=10,
        max_concurrent_jobs=5,
        lock_lease_ms=1000,
    )

    assert poller.worker_id == "test_worker_1"
    assert poller.poll_interval_seconds == 10
    assert poller.max_concurrent_jobs == 5
    assert poller.lock_lease_ms == 1000
    assert not poller.is_running


@pytest.mark.asyncio
async def test_scheduler_poller_poll(mock_sweep_use_case, mock_claim_use_case):
    poller = SchedulerPoller(
        sweep_use_case=mock_sweep_use_case,
        claim_use_case=mock_claim_use_case,
        worker_id="test_worker_2",
    )

    await poller.poll()

    mock_sweep_use_case.execute.assert_awaited_once_with(lock_lease_ms=poller.lock_lease_ms)
    mock_claim_use_case.execute.assert_awaited_once_with(
        worker_id="test_worker_2",
        limit=poller.max_concurrent_jobs,
        lock_lease_ms=poller.lock_lease_ms,
    )


@pytest.mark.asyncio
async def test_scheduler_poller_start_and_stop(mock_sweep_use_case, mock_claim_use_case):
    poller = SchedulerPoller(
        sweep_use_case=mock_sweep_use_case,
        claim_use_case=mock_claim_use_case,
        poll_interval_seconds=0,
    )

    # Let poll execute a couple of times then stop
    async def side_effect(*args, **kwargs):
        await poller.stop()

    mock_sweep_use_case.execute.side_effect = side_effect

    # Should run and exit
    await poller.start()

    assert not poller.is_running
    mock_sweep_use_case.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_scheduler_poller_exception_handling(mock_sweep_use_case, mock_claim_use_case):
    poller = SchedulerPoller(
        sweep_use_case=mock_sweep_use_case,
        claim_use_case=mock_claim_use_case,
        poll_interval_seconds=0,
    )

    call_count = 0

    async def side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Simulated error in poll")
        else:
            await poller.stop()

    mock_sweep_use_case.execute.side_effect = side_effect

    await poller.start()

    # The poller should catch the exception on the first pass and then stop on the second pass
    assert call_count == 2
    assert not poller.is_running
