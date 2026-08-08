from typing import Any, Protocol

from ..domain.models import Channel, Template


class TemplateRepositoryPort(Protocol):
    async def get_template(
        self, tenant_id: str, event_type: str, channel: Channel
    ) -> Template | None: ...


class TemplateRendererPort(Protocol):
    def render(self, template_str: str, data: dict[str, Any]) -> str: ...


class DeliveryStrategyPort(Protocol):
    async def deliver(
        self, tenant_id: str, content: str, subject: str | None, data: dict[str, Any]
    ) -> None: ...


class DeliveryDispatcherPort(Protocol):
    async def dispatch(
        self,
        channel: Channel,
        tenant_id: str,
        content: str,
        subject: str | None,
        data: dict[str, Any],
    ) -> None: ...
