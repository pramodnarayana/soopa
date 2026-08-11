import asyncio
import json

import pytest
from sqlalchemy import text

from notification_engine.adapters.inbound.postgres_listener import PostgresNotificationListener
from notification_engine.application.ports.notification_query_port import NotificationDTO


class FakeStreamManager:
    def __init__(self):
        self.broadcasts = []

    async def broadcast(self, tenant_id: str, user_id: str, notification: NotificationDTO) -> None:
        self.broadcasts.append((tenant_id, user_id, notification))


@pytest.mark.asyncio
async def test_postgres_listener_integration(postgres_container, db_engine):
    """
    A High-Quality Narrow Integration Test that uses a real Postgres container
    to verify that the asyncpg NOTIFY/LISTEN machinery works end-to-end.
    """
    db_url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )

    stream_manager = FakeStreamManager()

    # Start the real listener against the testcontainer db
    listener = PostgresNotificationListener(db_url, stream_manager, channel="in_app_notifications")
    listener.start()

    # Give it a moment to connect and execute ADD_LISTENER
    await asyncio.sleep(0.5)

    payload = json.dumps(
        {
            "tenant_id": "test-tenant",
            "user_id": "user-123",
            "id": "notif-777",
            "title": "Integration Title",
            "body": "Integration Body",
            "is_read": False,
            "created_at": "2026-08-11T12:00:00",
        }
    )

    # Issue a real NOTIFY command from the other connection
    async with db_engine.begin() as conn:
        # We must escape the single quotes in the payload if needed,
        # but the easiest way is to use bound parameters if possible.
        # Unfortunately, NOTIFY payload doesn't support parameterized queries natively in all dialects,
        # so we inject the json directly safely.
        await conn.execute(text(f"NOTIFY in_app_notifications, '{payload}'"))

    # Wait for the listener to pick it up and process it
    await asyncio.sleep(0.5)

    # Verify the event was received and parsed correctly
    assert len(stream_manager.broadcasts) == 1

    broadcasted = stream_manager.broadcasts[0]
    assert broadcasted[0] == "test-tenant"
    assert broadcasted[1] == "user-123"
    assert broadcasted[2].id == "notif-777"
    assert broadcasted[2].title == "Integration Title"

    # Clean up
    await listener.stop()
