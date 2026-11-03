from typing import Protocol

from notification.domain.enums import Channel


class NotificationRouteRepositoryPort(Protocol):
    async def get_channels(self, tenant_id: str, event_type: str) -> list[Channel]: ...
