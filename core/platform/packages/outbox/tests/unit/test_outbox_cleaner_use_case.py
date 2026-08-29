from unittest.mock import AsyncMock

import pytest
from outbox.application.outbox_cleaner_use_case import OutboxCleanerUseCase


@pytest.mark.asyncio
async def test_outbox_cleaner_execute_calls_repository_with_correct_retention_days():
    # Arrange
    repository = AsyncMock()
    repository.cleanup_outbox.return_value = 150  # 150 records deleted
    use_case = OutboxCleanerUseCase(repository=repository, retention_days=7)

    # Act
    await use_case.execute()

    # Assert
    repository.cleanup_outbox.assert_awaited_once_with(retention_days=7)


@pytest.mark.asyncio
async def test_outbox_cleaner_execute_uses_default_retention_days():
    # Arrange
    repository = AsyncMock()
    repository.cleanup_outbox.return_value = 0
    use_case = OutboxCleanerUseCase(repository=repository)  # default = 3 days

    # Act
    await use_case.execute()

    # Assert
    repository.cleanup_outbox.assert_awaited_once_with(retention_days=3)


@pytest.mark.asyncio
async def test_outbox_cleaner_execute_when_nothing_to_delete():
    # Arrange
    repository = AsyncMock()
    repository.cleanup_outbox.return_value = 0
    use_case = OutboxCleanerUseCase(repository=repository, retention_days=30)

    # Act — should complete without raising
    await use_case.execute()

    # Assert — repository was still called
    repository.cleanup_outbox.assert_awaited_once_with(retention_days=30)
