from typing import Any

import structlog

from worker.adapters.acl.base import EventTranslator
from worker.adapters.acl.ucp_translators import (
    TenantProvisionedTranslator,
    WebhookEventTranslator,
)

logger = structlog.get_logger(__name__)


class UcpEventNames:
    """Constants representing external UCP Event names."""

    TENANT_PROVISIONED = "tenant.provisioned"
    WEBHOOK_CREATED = "webhook.created"
    WEBHOOK_UPDATED = "webhook.updated"
    WEBHOOK_DELETED = "webhook.deleted"


# Registry mapping external event names to their concrete translator strategies
_TRANSLATOR_REGISTRY: dict[str, EventTranslator] = {
    UcpEventNames.TENANT_PROVISIONED: TenantProvisionedTranslator(),
    UcpEventNames.WEBHOOK_CREATED: WebhookEventTranslator(UcpEventNames.WEBHOOK_CREATED),
    UcpEventNames.WEBHOOK_UPDATED: WebhookEventTranslator(UcpEventNames.WEBHOOK_UPDATED),
    UcpEventNames.WEBHOOK_DELETED: WebhookEventTranslator(UcpEventNames.WEBHOOK_DELETED),
}


def translate_external_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    Translates an external event using the configured strategy in the registry.

    Args:
        event_type: The string identifier of the external event (e.g., 'TENANT_PROVISIONED')
        payload: The raw external JSON payload.

    Returns:
        The translated dictionary, or None if no translator was found.
    """
    translator = _TRANSLATOR_REGISTRY.get(event_type)
    if translator:
        try:
            return translator.translate(payload)
        except Exception:
            logger.exception(
                "Error translating external event '{event_type}'", event_type=event_type
            )

            raise

    return None
