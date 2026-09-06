from unittest.mock import AsyncMock, Mock

import pytest

from notification_worker import main


class FakeWorker:
    def __init__(self) -> None:
        self.start = Mock()
        self.stop = AsyncMock()
        self.task = None


@pytest.mark.asyncio
async def test_run_consumer_requires_sns_topic_arn_before_container_initialization(
    monkeypatch,
) -> None:
    monkeypatch.delenv("SNS_TOPIC_ARN", raising=False)
    container = Mock()
    monkeypatch.setattr(main, "Container", container)

    with pytest.raises(SystemExit) as exc_info:
        await main.run_consumer()

    assert exc_info.value.code == 1
    container.assert_not_called()


@pytest.mark.asyncio
async def test_run_consumer_preserves_worker_error_when_shutdown_fails(monkeypatch) -> None:
    worker_error = RuntimeError("worker failed")
    container = Mock()
    container.init_resources = AsyncMock()
    container.consumer_worker.return_value = FakeWorker()
    container.email_worker.return_value = FakeWorker()
    container.outbox_listener.return_value = FakeWorker()
    wait_for_workers = AsyncMock(side_effect=worker_error)
    graceful_shutdown = AsyncMock(side_effect=RuntimeError("shutdown failed"))
    monkeypatch.setattr(main, "_wait_and_handle_errors", wait_for_workers)
    monkeypatch.setattr(main, "_graceful_shutdown", graceful_shutdown)

    with pytest.raises(RuntimeError, match="worker failed") as exc_info:
        await main.run_consumer(stop_event=main.asyncio.Event(), container=container)

    assert exc_info.value is worker_error
    graceful_shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_graceful_shutdown_runs_every_cleanup_after_failure() -> None:
    outbox_listener = FakeWorker()
    consumer = FakeWorker()
    email_worker = FakeWorker()
    container = Mock()
    container.shutdown_resources = AsyncMock()
    outbox_listener.stop.side_effect = RuntimeError("outbox stop failed")

    with pytest.raises(RuntimeError, match="outbox stop failed"):
        await main._graceful_shutdown(outbox_listener, consumer, email_worker, container)

    consumer.stop.assert_awaited_once()
    email_worker.stop.assert_awaited_once()
    container.shutdown_resources.assert_awaited_once()
