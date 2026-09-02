import asyncio

from scheduler.application.job_sweeper_use_case import JobSweeperUseCase
from tests.fakes.fake_uow import FakeJobRepository, FakeSchedulerUow


def test_job_sweeper_use_case():
    repo = FakeJobRepository()
    repo.swept_count = 5

    def uow_factory():
        return FakeSchedulerUow(repo)

    use_case = JobSweeperUseCase(uow_factory=uow_factory)

    count = asyncio.run(use_case.execute(lock_lease_ms=5000))

    assert count == 5
