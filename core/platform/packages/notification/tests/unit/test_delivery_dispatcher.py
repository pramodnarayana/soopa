from typing import Any

import pytest

from notification.adapters.outbound.delivery_dispatcher import NotificationDeliveryDispatcher
from notification.domain.models import Channel
from notification.ports.notification_delivery_strategy_port import DeliveryStrategyPort


class FakeDeliveryStrategy(DeliveryStrategyPort):
    def __init__(self):
        self.deliveries = []

    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None:
        self.deliveries.append((tenant_id, content, subject, data))


@pytest.mark.asyncio
async def test_delivery_dispatcher_success():
    email = FakeDeliveryStrategy()
    in_app = FakeDeliveryStrategy()
    slack = FakeDeliveryStrategy()

    dispatcher = NotificationDeliveryDispatcher(email, in_app, slack)  # type: ignore

    await dispatcher.dispatch(Channel.EMAIL, "t1", "Email Content", "Email Subject", {"a": 1})
    await dispatcher.dispatch(Channel.IN_APP, "t1", "In App Content", None, {"a": 2})
    await dispatcher.dispatch(Channel.SLACK, "t1", "Slack Content", None, {"a": 3})

    assert len(email.deliveries) == 1
    assert email.deliveries[0] == ("t1", "Email Content", "Email Subject", {"a": 1})

    assert len(in_app.deliveries) == 1
    assert len(slack.deliveries) == 1


@pytest.mark.asyncio
async def test_delivery_dispatcher_missing_strategy():
    # What if a channel isn't registered? (Type system should theoretically prevent this, but testing safety guard)
    dispatcher = NotificationDeliveryDispatcher(
        FakeDeliveryStrategy(), FakeDeliveryStrategy(), FakeDeliveryStrategy()
    )  # type: ignore
    # Remove one dynamically
    del dispatcher.strategies[Channel.EMAIL]

    await dispatcher.dispatch(Channel.EMAIL, "t1", "Content", None, {})
    # Should not raise exception
