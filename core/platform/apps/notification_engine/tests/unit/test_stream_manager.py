import asyncio
from datetime import UTC, datetime

import pytest

from notification_engine.application.ports.notification_query_port import NotificationDTO
from notification_engine.application.stream_manager import NotificationStreamManager


@pytest.mark.asyncio
async def test_stream_manager_broadcast():
    manager = NotificationStreamManager()

    tenant_id = "tenant-1"
    user_id = "user-1"

    # Subscribe
    queue1 = manager.subscribe(tenant_id, user_id)
    queue2 = manager.subscribe(tenant_id, user_id)  # Same user, multiple tabs

    # Subscribe another user
    queue3 = manager.subscribe(tenant_id, "user-2")

    # Broadcast
    dto = NotificationDTO(
        id="n1",
        title="Test",
        body="Body",
        is_read=False,
        created_at=datetime.now(UTC),
        severity="info",
    )

    await manager.broadcast(tenant_id, user_id, dto)

    # Assert queues for user_id got the message
    msg1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    assert msg1.id == "n1"

    msg2 = await asyncio.wait_for(queue2.get(), timeout=1.0)
    assert msg2.id == "n1"

    # Assert other user did not get the message
    assert queue3.empty()

    # Unsubscribe
    manager.unsubscribe(tenant_id, user_id, queue1)
    manager.unsubscribe(tenant_id, user_id, queue2)
    manager.unsubscribe(tenant_id, "user-2", queue3)

    assert (tenant_id, user_id) not in manager._queues
