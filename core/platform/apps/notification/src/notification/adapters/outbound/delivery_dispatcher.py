import logging
from typing import Any

from ...domain.models import Channel
from ...ports.interfaces import DeliveryStrategyPort
from .channels import EmailDeliveryStrategy, InAppDeliveryStrategy, SlackDeliveryStrategy

logger = logging.getLogger(__name__)


class StrategyDeliveryDispatcher:
    def __init__(
        self,
        email_strategy: EmailDeliveryStrategy,
        in_app_strategy: InAppDeliveryStrategy,
        slack_strategy: SlackDeliveryStrategy,
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
            logger.warning(f"No delivery strategy found for channel {channel}")
            return

        await strategy.deliver(tenant_id, content, subject, data)
