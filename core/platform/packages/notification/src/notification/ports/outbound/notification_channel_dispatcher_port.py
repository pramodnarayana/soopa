from typing import Protocol

from seedwork.domain.types import JsonDict

from notification.domain.models import Channel


class ChannelDispatcherPort(Protocol):
    async def dispatch(
        self,
        channel: Channel,
        tenant_id: str,
        content: str,
        subject: str | None,
        data: JsonDict,
    ) -> None: ...
