from typing import Protocol

from seedwork.domain.types import JsonDict


class DeliveryStrategyPort(Protocol):
    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: JsonDict
    ) -> None: ...
