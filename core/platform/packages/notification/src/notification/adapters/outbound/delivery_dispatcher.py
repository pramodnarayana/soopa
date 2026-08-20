from typing import Any

import structlog

from ...domain.models import Channel
from ...ports.notification_delivery_strategy_port import DeliveryStrategyPort

logger = structlog.get_logger(__name__)


class NotificationDeliveryDispatcher:
    def __init__(
        self,
        email_strategy: DeliveryStrategyPort,
        in_app_strategy: DeliveryStrategyPort,
        slack_strategy: DeliveryStrategyPort,
    ):
        self.strategies: dict[Channel, DeliveryStrategyPort] = {
            Channel.EMAIL: email_strategy,
            Channel.IN_APP: in_app_strategy,
            Channel.SLACK: slack_strategy,
        }

    async def dispatch(
        self,
        channel: Channel,
        tenant_id: str,
        content: str,
        subject: str | None,
        data: dict[str, Any],
    ) -> None:
        strategy = self.strategies.get(channel)
        if not strategy:
            logger.warning("No delivery strategy found for channel {channel}", channel=channel)
            return

        await strategy.deliver(tenant_id, content, subject, data)
