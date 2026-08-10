from typing import Any, Protocol

from domain.events import EdiEventType, ProvisioningEvent


class ControlPlaneOutboxRepositoryPort(Protocol):
    async def publish_outbox_event(
        self,
        event: ProvisioningEvent,
        idempotency_key: str | None = None,
    ) -> str: ...

    async def get_event_by_idempotency_key(self, idempotency_key: str) -> Any | None: ...

    async def create_reservation(
        self, tenant_id: str, idempotency_key: str, fingerprint: str
    ) -> None: ...


class DataPlaneOutboxRepositoryPort(Protocol):
    async def publish_outbox_event(
        self,
        tenant_id: str,
        event_type: EdiEventType | str,
        payload: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> str: ...

    async def publish_outbox_events_bulk(
        self,
        tenant_id: str,
        events: list[dict[str, Any]],
    ) -> list[str]:
        """
        events is a list of dictionaries, each containing:
        {
            "event_type": EdiEventType | str,
            "payload": dict[str, Any],
            "idempotency_key": str | None
        }
        """
        ...
