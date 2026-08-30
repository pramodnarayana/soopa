import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ucp_worker.main import main


@pytest.mark.asyncio
async def test_main_bootstrap_and_cancellation() -> None:
    """Test that main initializes the container and can be cancelled cleanly."""

    with patch("ucp_worker.main.AwsSqsConsumer") as mock_consumer_class:
        mock_consumer = MagicMock()
        mock_consumer_class.return_value = mock_consumer

        class MockActiveConsumer:
            def poll_raw_message(self) -> Any:
                class MockPollRawMessage:
                    async def __aenter__(self) -> Any:
                        raise asyncio.CancelledError()

                    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
                        pass

                return MockPollRawMessage()

        mock_consumer.__aenter__ = AsyncMock(return_value=MockActiveConsumer())
        mock_consumer.__aexit__ = AsyncMock(return_value=None)

        with patch("ucp_worker.main.WorkerContainer") as mock_container_class:
            mock_container = mock_container_class.return_value
            mock_container.settings.sqs_ucp_jobs_queue_url = "https://sqs.mock/queue"
            mock_container.settings.aws_region = "us-east-1"
            mock_container.settings.aws_endpoint_url = None

            mock_container.outbox_relay = MagicMock()
            mock_container.outbox_relay.stop = AsyncMock()
            mock_container.events_consumer = MagicMock()
            mock_container.events_consumer.stop = AsyncMock()
            mock_container.dispose = AsyncMock()

            # Run main. It should catch the CancelledError in the poll loop and then cleanly shutdown.
            await main()

            mock_container.wire.assert_called_once()
            mock_container.outbox_relay.start.assert_called_once()
            mock_container.events_consumer.start.assert_called_once()
            mock_container.outbox_relay.stop.assert_awaited_once()
            mock_container.events_consumer.stop.assert_awaited_once()
            mock_container.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_poll_loop_exception() -> None:
    """Test that main raises if an unexpected exception occurs in the poll loop."""

    with patch("ucp_worker.main.AwsSqsConsumer") as mock_consumer_class:
        mock_consumer = MagicMock()
        mock_consumer_class.return_value = mock_consumer

        class MockActiveConsumer:
            def poll_raw_message(self) -> Any:
                class MockPollRawMessageError:
                    async def __aenter__(self) -> Any:
                        raise RuntimeError("Unexpected DB failure")

                    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
                        pass

                return MockPollRawMessageError()

        mock_consumer.__aenter__ = AsyncMock(return_value=MockActiveConsumer())
        mock_consumer.__aexit__ = AsyncMock(return_value=None)

        with patch("ucp_worker.main.WorkerContainer") as mock_container_class:
            mock_container = mock_container_class.return_value
            mock_container.outbox_relay = MagicMock()
            mock_container.outbox_relay.stop = AsyncMock()
            mock_container.events_consumer = MagicMock()
            mock_container.events_consumer.stop = AsyncMock()
            mock_container.dispose = AsyncMock()

            with pytest.raises(RuntimeError, match="Unexpected DB failure"):
                await main()
