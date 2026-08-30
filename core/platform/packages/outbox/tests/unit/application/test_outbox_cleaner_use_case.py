import pytest
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase
from outbox.testing.fakes import FakeOutboxCleanupRepository


@pytest.mark.asyncio
async def test_outbox_cleaner_execute_calls_repository_with_correct_retention_days():
    repository = FakeOutboxCleanupRepository()
    use_case = OutboxCleanerUseCase(repository=repository, retention_days=7)

    await use_case.execute()

    assert repository.cleanup_calls == [7]


@pytest.mark.asyncio
async def test_outbox_cleaner_execute_uses_default_retention_days():
    repository = FakeOutboxCleanupRepository()
    use_case = OutboxCleanerUseCase(repository=repository)  # default = 3 days

    await use_case.execute()

    assert repository.cleanup_calls == [3]


@pytest.mark.asyncio
async def test_outbox_cleaner_execute_when_nothing_to_delete():
    repository = FakeOutboxCleanupRepository()
    use_case = OutboxCleanerUseCase(repository=repository, retention_days=30)

    await use_case.execute()

    assert repository.cleanup_calls == [30]
