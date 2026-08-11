import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from notification_engine.adapters.inbound.postgres_listener import PostgresNotificationListener
from notification_engine.application.ports.notification_query_port import NotificationDTO


class FakeStreamManager:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, tenant_id: str, user_id: str, notification: NotificationDTO) -> None:
        self.broadcasts.append((tenant_id, user_id, notification))


@pytest.mark.asyncio
async def test_postgres_listener_on_notify():
    stream_manager = FakeStreamManager()
    listener = PostgresNotificationListener("postgresql+asyncpg://foo", stream_manager)  # type: ignore

    payload = json.dumps(
        {
            "tenant_id": "t1",
            "user_id": "u1",
            "id": "123",
            "title": "Test",
            "body": "Hello",
            "is_read": False,
            "created_at": "2026-08-11T12:00:00",
        }
    )

    # Simulate asyncpg calling the callback
    listener._on_notify(None, 1234, "channel", payload)  # type: ignore

    # Allow the fire-and-forget task to run
    await asyncio.sleep(0.01)

    assert len(stream_manager.broadcasts) == 1
    assert stream_manager.broadcasts[0][0] == "t1"
    assert stream_manager.broadcasts[0][1] == "u1"
    assert stream_manager.broadcasts[0][2].id == "123"
    assert stream_manager.broadcasts[0][2].title == "Test"


@pytest.mark.asyncio
async def test_postgres_listener_on_notify_malformed():
    stream_manager = FakeStreamManager()
    listener = PostgresNotificationListener("postgresql://foo", stream_manager)  # type: ignore

    # Missing tenant_id
    payload = json.dumps(
        {
            "user_id": "u1",
            "id": "123",
            "title": "Test",
            "body": "Hello",
        }
    )

    listener._on_notify(None, 1234, "channel", payload)  # type: ignore

    await asyncio.sleep(0.01)
    assert len(stream_manager.broadcasts) == 0


@pytest.mark.asyncio
async def test_postgres_listener_lifecycle():
    stream_manager = FakeStreamManager()
    listener = PostgresNotificationListener("postgresql://foo", stream_manager)  # type: ignore

    with patch(
        "notification_engine.adapters.inbound.postgres_listener.asyncpg.connect",
        new_callable=AsyncMock,
    ) as mock_connect:
        from unittest.mock import MagicMock

        mock_conn = MagicMock()
        mock_conn.is_closed.return_value = False
        mock_conn.add_listener = AsyncMock()
        mock_conn.remove_listener = AsyncMock()
        mock_conn.close = AsyncMock()
        mock_connect.return_value = mock_conn

        listener.start()
        assert listener.is_running is True

        # Start again does nothing
        listener.start()

        await asyncio.sleep(0.01)

        await listener.stop()

        assert listener.is_running is False
        mock_connect.assert_called_once()
        mock_conn.add_listener.assert_called_once()
        mock_conn.remove_listener.assert_called_once()
        mock_conn.close.assert_called_once()
