from typing import Any

import pytest
from notification.adapters.outbound.channels import EmailChannelStrategy

from notification_email_worker.adapters.inbound.workers.email_channel_dispatcher import (
    EmailChannelDispatcher,
)


class FakeEmailChannelStrategy(EmailChannelStrategy):
    def __init__(self) -> None:
        self.deliveries: list[dict[str, Any]] = []

    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        self.deliveries.append(
            {
                "tenant_id": tenant_id,
                "content": content,
                "subject": subject,
                "data": data,
            }
        )


@pytest.mark.asyncio
async def test_dispatch_raw_delivers_valid_email_request() -> None:
    strategy = FakeEmailChannelStrategy()
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

    assert len(strategy.deliveries) == 1
    assert strategy.deliveries[0] == {
        "tenant_id": "tenant-1",
        "content": "Hello",
        "subject": "Welcome",
        "data": {"recipient": "user@example.com"},
    }


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
    strategy = FakeEmailChannelStrategy()
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

    assert len(strategy.deliveries) == 0
