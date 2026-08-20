from typing import Any, Protocol


class DeliveryStrategyPort(Protocol):
    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None: ...
