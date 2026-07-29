from typing import Any

from domain.events import ProvisioningEventType

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

        name = (nested_payload.get("name") if nested_payload else None) or external_payload.get(
            "name"
        )

        if not tenant_id:
            raise ValueError("Malformed provisioning event: tenant identifier not found")

        # Re-map to match Orchestrator's internal schema requirements
        return {
            "event_type": ProvisioningEventType.PROVISION_TENANT.value,
            "payload": {
                "tenant_id": tenant_id,
                "name": name,
            },
        }


