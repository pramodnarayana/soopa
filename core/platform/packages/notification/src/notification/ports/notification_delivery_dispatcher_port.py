from typing import Any, Protocol

from notification.domain.models import Channel


class DeliveryDispatcherPort(Protocol):
    async def dispatch(
        self,
        channel: Channel,
        tenant_id: str,
        content: str,
        subject: str | None,
        data: dict[str, Any],
    ) -> None: ...
