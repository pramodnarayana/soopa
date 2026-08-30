import pytest
from structlog.testing import capture_logs

from notification.adapters.outbound.channels.in_app_delivery_strategy import (
    InAppDeliveryStrategy,
)


@pytest.mark.asyncio
async def test_in_app_delivery_strategy():
    strategy = InAppDeliveryStrategy()

    with capture_logs() as cap_logs:
        await strategy.deliver(
            tenant_id="ten_123",
            content="Hello",
            subject="Subj",
            data={"k": "v"},
        )

    # Assert logs are written. In-app delivery just logs for now.
    assert any(log["event"] == "in_app_notification_delivering" for log in cap_logs)
