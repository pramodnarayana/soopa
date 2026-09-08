from unittest.mock import AsyncMock

import pytest
from notification.adapters.outbound.channels import EmailChannelStrategy

from notification_email_worker.adapters.inbound.workers.email_channel_dispatcher import (
    EmailChannelDispatcher,
)


@pytest.mark.asyncio
async def test_dispatch_raw_delivers_valid_email_request() -> None:
    strategy = AsyncMock(spec=EmailChannelStrategy)
    dispatcher = EmailChannelDispatcher(strategy)

    await dispatcher.dispatch_raw(
        {
            "event_type": "email.requested",
            "tenant_id": "tenant-1",
            "payload": {
                "content": "Hello",
                "subject": "Welcome",
                "data": {"recipient": "user@example.com"},
            },
        }
    )

    strategy.deliver.assert_awaited_once_with(
        tenant_id="tenant-1",
        content="Hello",
        subject="Welcome",
        data={"recipient": "user@example.com"},
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tenant_id", "content", "subject", "data"),
    [
        (None, "Hello", "Welcome", {}),
        ("", "Hello", "Welcome", {}),
        (123, "Hello", "Welcome", {}),
        ("tenant-1", None, "Welcome", {}),
        ("tenant-1", "", "Welcome", {}),
        ("tenant-1", 123, "Welcome", {}),
        ("tenant-1", "Hello", 123, {}),
        ("tenant-1", "Hello", "Welcome", []),
    ],
)
async def test_dispatch_raw_rejects_invalid_delivery_payload(
    tenant_id: object,
    content: object,
    subject: object,
    data: object,
) -> None:
    strategy = AsyncMock(spec=EmailChannelStrategy)
    dispatcher = EmailChannelDispatcher(strategy)

    await dispatcher.dispatch_raw(
        {
            "event_type": "email.requested",
            "tenant_id": tenant_id,
            "payload": {
                "content": content,
                "subject": subject,
                "data": data,
            },
        }
    )

    strategy.deliver.assert_not_awaited()
