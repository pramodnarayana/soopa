from typing import Any

from worker.adapters.acl.base import EventTranslator


class WebhookEventTranslator(EventTranslator):
    """
    Translates a UCP Webhook event to an EDI provisioning event.
    """

    def __init__(self, event_type: str):
        self.event_type = event_type

    def translate(self, external_payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(external_payload, dict):
            raise TypeError("Malformed webhook event: payload must be a mapping")

        nested_payload = external_payload.get("payload")
        if nested_payload is not None and not isinstance(nested_payload, dict):
            nested_payload = {}

        tenant_id = (
            (nested_payload.get("tenantId") if nested_payload else None)
            or (nested_payload.get("tenant_id") if nested_payload else None)
            or external_payload.get("tenantId")
            or external_payload.get("tenant_id")
        )

        resource_id = (
            (nested_payload.get("webhook_id") if nested_payload else None)
            or (nested_payload.get("resource_id") if nested_payload else None)
            or external_payload.get("webhook_id")
            or external_payload.get("resource_id")
            or external_payload.get("id")
        )

        if not tenant_id:
            raise ValueError("Malformed webhook event: tenant identifier not found")

        return {
            "tenant_id": tenant_id,
            "event_type": self.event_type,
            "resource_id": resource_id,
        }
