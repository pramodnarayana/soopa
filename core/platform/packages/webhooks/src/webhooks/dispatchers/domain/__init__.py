"""Domain definitions for webhook dispatchers."""

from webhooks.dispatchers.domain.models import WebhookDeliveryResult, WebhookDispatchCommand

__all__ = [
    "WebhookDeliveryResult",
    "WebhookDispatchCommand",
]
