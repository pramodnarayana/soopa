from collections.abc import Mapping
from typing import Any

import pytest
from identity.domain.constants import IdentityIdPrefix
from seedwork.utils import generate_id
from structlog.testing import capture_logs

from notification.adapters.outbound.channels.slack_delivery_strategy import (
    DeliveryError,
    SlackDeliveryStrategy,
    SlackIntegrationPort,
)


class FakeSlackIntegration(SlackIntegrationPort):
    def __init__(self):
        self.sent_messages = []

    async def send_message(
        self, tenant_id: str, content: str, subject: str | None, data: Mapping[str, Any]
    ) -> None:
        self.sent_messages.append(
            {
                "tenant_id": tenant_id,
                "content": content,
                "subject": subject,
                "data": data,
            }
        )


@pytest.mark.asyncio
async def test_slack_delivery_strategy_delivers():
    integration = FakeSlackIntegration()
    strategy = SlackDeliveryStrategy(slack_integration=integration)

    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    with capture_logs() as cap_logs:
        await strategy.deliver(
            tenant_id=tenant_id,
            content="Hello Slack",
            subject=None,
            data={"k": "v"},
        )

    assert len(integration.sent_messages) == 1
    assert integration.sent_messages[0]["tenant_id"] == tenant_id
    assert integration.sent_messages[0]["content"] == "Hello Slack"

    assert any(log["event"] == "slack_message_delivering" for log in cap_logs)


@pytest.mark.asyncio
async def test_slack_delivery_strategy_fails_without_integration():
    strategy = SlackDeliveryStrategy(slack_integration=None)

    tenant_id = generate_id(IdentityIdPrefix.TENANT)
    with pytest.raises(DeliveryError, match="Slack integration not configured"):
        await strategy.deliver(
            tenant_id=tenant_id,
            content="Hello Slack",
            subject=None,
            data={"k": "v"},
        )
