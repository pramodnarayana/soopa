from typing import Any

from domain.events import ProvisioningEventType

from worker.adapters.acl.base import EventTranslator


class TenantProvisionedTranslator(EventTranslator):
    """
    Translates a UCP 'TENANT_PROVISIONED' event to an EDI 'provision_tenant' event.
    """

    def translate(self, external_payload: dict[str, Any]) -> dict[str, Any]:
        # Handle both flat payload and nested 'payload' structure from UCP
        tenant_id = (
            external_payload.get("payload", {}).get("tenantId")
            or external_payload.get("payload", {}).get("id")
            or external_payload.get("tenantId")
            or external_payload.get("id")
        )

        name = external_payload.get("payload", {}).get("name") or external_payload.get("name")

        if not tenant_id:
            # Fallback or log/raise in an enterprise setting; we'll return as is to fail validation
            return external_payload

        # Re-map to match Orchestrator's internal schema requirements
        return {
            "event_type": ProvisioningEventType.PROVISION_TENANT.value,
            "payload": {
                "tenant_id": tenant_id,
                "name": name,
            },
        }


class TenantDeletedTranslator(EventTranslator):
    """
    Placeholder for future translation logic.
    """

    def translate(self, external_payload: dict[str, Any]) -> dict[str, Any]:
        return external_payload
