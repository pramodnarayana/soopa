import asyncio

import pytest

from scheduler_worker.adapters.inbound.workers.scheduler_poller import SchedulerPoller


class FakeSweeperUseCase:
    def __init__(self, poller_to_stop: SchedulerPoller | None = None, raise_error: bool = False):
        self.call_count = 0
        self.poller_to_stop = poller_to_stop
        self.raise_error = raise_error

    async def execute(self, lock_lease_ms: int) -> None:
        self.call_count += 1
        if self.raise_error:
            raise RuntimeError("Fake sweep error")
        if self.poller_to_stop:
            await self.poller_to_stop.stop()


class FakeClaimUseCase:
    def __init__(self) -> None:
        self.call_count = 0

    async def execute(self, worker_id: str, limit: int, lock_lease_ms: int) -> None:
        self.call_count += 1


@pytest.mark.asyncio
async def test_scheduler_poller_polls_successfully() -> None:
    sweeper: FakeSweeperUseCase = FakeSweeperUseCase()
    claimer: FakeClaimUseCase = FakeClaimUseCase()

    poller = SchedulerPoller(
        sweep_use_case=sweeper,  # type: ignore[arg-type]
        claim_use_case=claimer,  # type: ignore[arg-type]
        worker_id="test_worker",
        poll_interval_seconds=0,
    )

    # Inject the poller into the sweeper so it stops the loop after 1 iteration
    sweeper.poller_to_stop = poller

    # start() will block until stop() is called, which happens during the first poll()
    await poller.start()

    assert sweeper.call_count == 1
    assert claimer.call_count == 1
    assert poller.is_running is False


@pytest.mark.asyncio
async def test_scheduler_poller_continues_on_exception() -> None:
    sweeper: FakeSweeperUseCase = FakeSweeperUseCase(raise_error=True)
    claimer: FakeClaimUseCase = FakeClaimUseCase()

    poller = SchedulerPoller(
        sweep_use_case=sweeper,  # type: ignore[arg-type]
        claim_use_case=claimer,  # type: ignore[arg-type]
        worker_id="test_worker",
        poll_interval_seconds=0,
    )

    # To prevent an infinite loop, we run start() as a task, let it run briefly, then stop it.
    task = asyncio.create_task(poller.start())

    # Yield control to the event loop until the sweeper has been called at least twice
    while sweeper.call_count < 2:
        await asyncio.sleep(0.01)

    # Now stop the poller
    await poller.stop()
    await task

    # Sweeper should have been called at least twice
    assert sweeper.call_count >= 2
    # Claimer is never called because sweeper raises an error first
    assert claimer.call_count == 0
    assert poller.is_running is False
