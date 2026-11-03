from typing import Protocol

from edi.domain.events import OutboxEvent


class ControlPlaneOutboxRepositoryPort(Protocol):
    async def get_event_by_idempotency_key(self, idempotency_key: str) -> OutboxEvent | None: ...

    async def create_reservation(
        self, tenant_id: str, idempotency_key: str, fingerprint: str
    ) -> None: ...
