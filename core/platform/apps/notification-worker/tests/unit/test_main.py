from unittest.mock import Mock

import pytest

from notification_worker import main


@pytest.mark.asyncio
async def test_run_consumer_requires_sns_topic_arn_before_container_initialization(
    monkeypatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/notifications")
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)
    container = Mock()
    monkeypatch.setattr(main, "Container", container)

    with pytest.raises(SystemExit) as exc_info:
        await main.run_consumer()

    assert exc_info.value.code == 1
    container.assert_not_called()
