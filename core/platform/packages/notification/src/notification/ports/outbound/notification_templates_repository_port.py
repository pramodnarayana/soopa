from typing import Protocol

from notification.domain.models import Template


class NotificationTemplatesRepositoryPort(Protocol):
    """Port for reading and writing tenant Jinja2 notification templates."""

    async def list_templates(self, tenant_id: str) -> list[Template]: ...

    async def upsert_template(
        self,
        tenant_id: str,
        name: str,
        event_type: str,
        channel: str,
        subject_template: str | None,
        body_template: str,
        is_active: bool,
    ) -> Template: ...

    async def delete_template(self, tenant_id: str, template_id: str) -> bool: ...
