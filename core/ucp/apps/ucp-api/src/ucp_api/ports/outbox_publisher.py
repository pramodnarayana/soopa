from typing import Protocol
from ucp_models.events import ControlPlaneOutbox


class OutboxPublisherPort(Protocol):
    async def publish(self, event: ControlPlaneOutbox) -> None: ...
