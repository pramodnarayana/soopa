from typing import Any

from domain.events import LegacyUcpEventType

from worker.adapters.acl.base import EventTranslator


class TenantProvisionedTranslator(EventTranslator):
    """
    Translates a UCP 'TENANT_PROVISIONED' event to an EDI 'provision_tenant' event.
    """

    def translate(self, external_payload: dict[str, Any]) -> dict[str, Any]:
        # Normalize to dict if needed
        if not isinstance(external_payload, dict):
            raise ValueError("Malformed provisioning event: payload must be a mapping")

        # Handle both flat payload and nested 'payload' structure from UCP
        nested_payload = external_payload.get("payload")
        if nested_payload is not None and not isinstance(nested_payload, dict):
            nested_payload = {}

        tenant_id = (
            (nested_payload.get("tenantId") if nested_payload else None)
            or (nested_payload.get("id") if nested_payload else None)
            or external_payload.get("tenantId")
            or external_payload.get("id")
        )

        if not tenant_id:
            raise ValueError("Malformed provisioning event: tenant identifier not found")

        # Re-map to match Orchestrator's internal schema requirements
        # Re-map to match Orchestrator's internal schema requirements (flat ProvisioningEvent)
        return {
            "tenant_id": tenant_id,
            "event_type": LegacyUcpEventType.PROVISION_TENANT.value,
            "resource_id": tenant_id,
        }


class WebhookEventTranslator(EventTranslator):
    """
    Translates a UCP Webhook event to an EDI provisioning event.
    """

    def __init__(self, event_type: str):
        self.event_type = event_type

    def translate(self, external_payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(external_payload, dict):
            raise ValueError("Malformed webhook event: payload must be a mapping")

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
            (nested_payload.get("resource_id") if nested_payload else None)
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
