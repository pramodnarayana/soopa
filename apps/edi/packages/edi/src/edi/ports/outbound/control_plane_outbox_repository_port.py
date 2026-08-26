from typing import Any, Protocol

from edi.domain.events import ProvisioningEvent


class ControlPlaneOutboxRepositoryPort(Protocol):
    async def publish_outbox_event(
        self, event: ProvisioningEvent, idempotency_key: str | None = None
    ) -> str: ...

    async def get_event_by_idempotency_key(self, idempotency_key: str) -> Any | None: ...

    async def create_reservation(
        self, tenant_id: str, idempotency_key: str, fingerprint: str
    ) -> None: ...
