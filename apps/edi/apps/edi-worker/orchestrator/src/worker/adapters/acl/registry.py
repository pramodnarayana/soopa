import logging
from typing import Any

from worker.adapters.acl.base import EventTranslator
from worker.adapters.acl.ucp_translators import (
    TenantProvisionedTranslator,
)

logger = logging.getLogger(__name__)


class UcpEventNames:
    """Constants representing external UCP Event names."""

    TENANT_PROVISIONED = "tenant.provisioned"


# Registry mapping external event names to their concrete translator strategies
_TRANSLATOR_REGISTRY: dict[str, EventTranslator] = {
    UcpEventNames.TENANT_PROVISIONED: TenantProvisionedTranslator(),
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
        except Exception as e:
            logger.exception(f"Error translating external event '{event_type}': {e}")
            raise

    return None
