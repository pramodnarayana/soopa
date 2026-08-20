from typing import Protocol

from notification.domain.models import Channel, Template


class TemplateRepositoryPort(Protocol):
    async def get_template(
        self, tenant_id: str, event_type: str, channel: Channel
    ) -> Template | None: ...
